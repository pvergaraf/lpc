from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import login
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.core.mail import send_mail
from django.urls import reverse, reverse_lazy
from django.utils.crypto import get_random_string
from django.http import HttpResponseForbidden, JsonResponse
from django.db import transaction
from .models import Team, TeamMember, Season, Match, Profile, Payment, PlayerPayment
from .forms import (
    UserRegistrationForm, TeamMemberInviteForm, TeamForm, 
    EmailAuthenticationForm, AddTeamMemberForm, UserProfileForm,
    SeasonForm, MatchForm, AdminMemberProfileForm, PaymentForm, PlayerPaymentFormSet
)
from django.db import models
from django.contrib.auth.views import LogoutView
from django.utils import timezone
from django.conf import settings
from django.template.loader import render_to_string
from django.db.models import Case, When, Value, IntegerField
from .utils.logging_utils import log_error, log_upload_error
import os
import traceback
import secrets
import json

User = get_user_model()

def get_current_team(user):
    """Get the current team for a user from their session or active memberships."""
    # Get all active team memberships for the user
    team_memberships = TeamMember.objects.filter(
        user=user,
        is_active=True
    ).select_related('team')
    
    if not team_memberships.exists():
        return None

    # If there's only one team, return it
    if team_memberships.count() == 1:
        return team_memberships.first().team

    # Try to get team from session
    current_team_id = user.request.session.get('current_team') if hasattr(user, 'request') else None
    
    if current_team_id:
        # Verify the team from session is in user's active teams
        team_from_session = team_memberships.filter(team_id=current_team_id).first()
        if team_from_session:
            return team_from_session.team
    
    # If no team in session or invalid, return first active team
    return team_memberships.first().team

def get_current_season(team):
    """Get the current season for a team."""
    if not team:
        return None
        
    # First try to get the active season
    current_season = Season.objects.filter(
        team=team,
        is_active=True
    ).first()
    
    # If no active season, try to find a current season based on dates
    if not current_season:
        today = timezone.now().date()
        current_season = Season.objects.filter(
            team=team,
            start_date__lte=today,
            end_date__gte=today
        ).first()
        
        # If we found a current season by date, make it active
        if current_season:
            current_season.is_active = True
            current_season.save()
            
    return current_season

def is_user_team_admin(user, team):
    """Check if a user is an admin for a team."""
    return TeamMember.objects.filter(
        user=user,
        team=team,
        is_active=True,
        is_team_admin=True
    ).exists()

def is_admin(user):
    return user.is_superuser

@login_required
def dashboard(request):
    if not request.user.is_authenticated:
        log_error(
            request=request,
            error_message="Unauthenticated access attempt to dashboard",
            error_type="AuthenticationError",
            extra_context={
                "user_email": getattr(request.user, 'email', 'anonymous'),
                "path": request.path
            }
        )
        return redirect('teams:login')

    # Attach request to user for session access
    request.user.request = request
    current_team = get_current_team(request.user)
    
    # Get the filter parameter
    show_active_only = request.GET.get('active_only', 'false').lower() == 'true'
    
    log_error(  # Using log_error for all logging until we create a dedicated operational logging function
        request=request,
        error_message="Dashboard access",
        error_type="UserActivity",
        extra_context={
            "user_email": request.user.email,
            "user_id": request.user.id,
            "current_team": current_team.id if current_team else None,
            "path": request.path,
            "method": request.method,
            "timestamp": timezone.now().isoformat(),
            "show_active_only": show_active_only
        }
    )
    
    if not current_team:
        log_error(
            request=request,
            error_message="User has no active teams",
            error_type="TeamAccess",
            extra_context={
                "user_email": request.user.email,
                "user_id": request.user.id
            }
        )
        messages.warning(request, "You are not a member of any team. Please join or create a team.")
        return redirect('teams:team_list')

    try:
        # Get the user's team membership
        team_member = TeamMember.objects.get(
            team=current_team,
            user=request.user,
            is_active=True
        )
        
        log_error(
            request=request,
            error_message="Team member details loaded",
            error_type="TeamAccess",
            extra_context={
                "user_email": request.user.email,
                "user_id": request.user.id,
                "team_id": current_team.id,
                "team_name": current_team.name,
                "role": team_member.role,
                "is_admin": team_member.is_team_admin
            }
        )
    except TeamMember.DoesNotExist:
        log_error(
            request=request,
            error_message="Invalid team membership access attempt",
            error_type="TeamAccessError",
            extra_context={
                "user_email": request.user.email,
                "user_id": request.user.id,
                "team_id": current_team.id,
                "team_name": current_team.name
            }
        )
        messages.error(request, "There was an error accessing your team membership.")
        return redirect('teams:team_list')

    current_season = get_current_season(current_team)
    is_team_admin = is_user_team_admin(request.user, current_team)
    today = timezone.now().date()

    # Get pending payments for the current user
    pending_payments = PlayerPayment.objects.filter(
        player__user=request.user,
        player__team=current_team,
        payment__season=current_season,
        amount__gt=0  # Only show payments with amount > 0
    ).select_related('payment')

    # Log payment status
    log_error(
        request=request,
        error_message="Payment status check",
        error_type="PaymentActivity",
        extra_context={
            "user_email": request.user.email,
            "user_id": request.user.id,
            "team_id": current_team.id,
            "season_id": current_season.id if current_season else None,
            "pending_payments_count": pending_payments.count(),
            "total_pending_amount": sum(p.amount for p in pending_payments)
        }
    )

    # Get team memberships for the teams list
    team_memberships = TeamMember.objects.filter(
        user=request.user,
        is_active=True
    ).select_related('team')

    # Get team members for the current team
    team_members_query = TeamMember.objects.filter(
        team=current_team
    ).filter(
        models.Q(is_active=True) | 
        models.Q(is_active=False, invitation_token__isnull=False)
    )
    
    # Apply active filter if requested
    if show_active_only:
        team_members_query = team_members_query.filter(user__profile__active_player=True)
    
    team_members = team_members_query.select_related(
        'user', 
        'user__profile', 
        'user__profile__position'
    ).annotate(
        position_order=Case(
            When(user__profile__position__type='GK', then=Value(1)),
            When(user__profile__position__type='DEF', then=Value(2)),
            When(user__profile__position__type='MID', then=Value(3)),
            When(user__profile__position__type='ATT', then=Value(4)),
            default=Value(5),
            output_field=IntegerField(),
        )
    ).order_by(
        'position_order',
        'user__profile__player_number'
    )

    # Log team composition
    log_error(
        request=request,
        error_message="Team composition loaded",
        error_type="TeamActivity",
        extra_context={
            "user_email": request.user.email,
            "user_id": request.user.id,
            "team_id": current_team.id,
            "team_name": current_team.name,
            "active_members_count": team_members.count(),
            "pending_invitations_count": team_members.filter(is_active=False, invitation_token__isnull=False).count(),
            "total_teams": team_memberships.count()
        }
    )

    # Get upcoming matches if there's a current season
    upcoming_matches = None
    if current_season:
        upcoming_matches = Match.objects.filter(
            season=current_season,
            match_date__gte=today
        ).order_by('match_date', 'match_time')
        
        # Log upcoming matches
        log_error(
            request=request,
            error_message="Upcoming matches loaded",
            error_type="MatchActivity",
            extra_context={
                "user_email": request.user.email,
                "user_id": request.user.id,
                "team_id": current_team.id,
                "season_id": current_season.id,
                "upcoming_matches_count": upcoming_matches.count(),
                "next_match_date": upcoming_matches.first().match_date.isoformat() if upcoming_matches.exists() else None
            }
        )

    context = {
        'current_team': current_team,
        'current_season': current_season,
        'is_team_admin': is_team_admin,
        'pending_payments': pending_payments,
        'today': today.isoformat(),
        'team_memberships': team_memberships,
        'team_members': team_members,
        'upcoming_matches': upcoming_matches,
    }

    # Log successful dashboard render
    log_error(
        request=request,
        error_message="Dashboard rendered successfully",
        error_type="PageView",
        extra_context={
            "user_email": request.user.email,
            "user_id": request.user.id,
            "team_id": current_team.id,
            "team_name": current_team.name,
            "is_admin": is_team_admin,
            "has_season": bool(current_season),
            "render_timestamp": timezone.now().isoformat()
        }
    )

    return render(request, 'teams/dashboard.html', context)

@login_required
def switch_team(request, team_id):
    log_error(
        request=request,
        error_message="Team switch initiated",
        error_type="UserActivity",
        extra_context={
            "user_email": request.user.email,
            "user_id": request.user.id,
            "current_team_id": request.session.get('current_team'),
            "target_team_id": team_id,
            "path": request.path,
            "method": request.method
        }
    )
    
    try:
        team_member = get_object_or_404(TeamMember, team_id=team_id, user=request.user, is_active=True)
        request.session['current_team'] = team_id
        
        log_error(
            request=request,
            error_message="Team switch successful",
            error_type="UserActivity",
            extra_context={
                "user_email": request.user.email,
                "user_id": request.user.id,
                "new_team_id": team_id,
                "new_team_name": team_member.team.name,
                "role": team_member.role,
                "is_admin": team_member.is_team_admin
            }
        )
        return redirect('teams:dashboard')
    except TeamMember.DoesNotExist:
        log_error(
            request=request,
            error_message="Team switch failed - Invalid membership",
            error_type="AuthorizationError",
            extra_context={
                "user_email": request.user.email,
                "user_id": request.user.id,
                "attempted_team_id": team_id
            }
        )
        messages.error(request, "You are not a member of this team.")
        return redirect('teams:team_list')
    except Exception as e:
        log_error(
            request=request,
            error_message=f"Team switch failed: {str(e)}",
            error_type="SystemError",
            extra_context={
                "user_email": request.user.email,
                "user_id": request.user.id,
                "attempted_team_id": team_id,
                "error": str(e),
                "error_type": type(e).__name__,
                "traceback": traceback.format_exc()
            }
        )
        messages.error(request, "An error occurred while switching teams.")
        return redirect('teams:team_list')

class CustomLogoutView(LogoutView):
    next_page = reverse_lazy('teams:login')
    http_method_names = ['get', 'post']
    template_name = 'teams/logout.html'
    
    def dispatch(self, request, *args, **kwargs):
        # Clear any custom session data
        request.session.flush()
        return super().dispatch(request, *args, **kwargs)

@login_required
def team_members(request, team_id):
    log_error(
        request=request,
        error_message="Team members page access",
        error_type="UserActivity",
        extra_context={
            "user_email": request.user.email,
            "user_id": request.user.id,
            "team_id": team_id,
            "path": request.path,
            "method": request.method
        }
    )
    
    try:
        team = get_object_or_404(Team, id=team_id)
        team_member = get_object_or_404(TeamMember, team=team, user=request.user, is_active=True)
        
        # Get the filter parameter
        show_active_only = request.GET.get('active_only', 'false').lower() == 'true'
        
        # Get active members
        active_members_query = TeamMember.objects.filter(
            team=team,
            is_active=True
        )
        
        # Apply active filter if requested
        if show_active_only:
            active_members_query = active_members_query.filter(user__profile__active_player=True)
        
        active_members = active_members_query.select_related(
            'user', 
            'user__profile',
            'user__profile__position'
        ).annotate(
            position_order=Case(
                When(user__profile__position__type='GK', then=Value(1)),
                When(user__profile__position__type='DEF', then=Value(2)),
                When(user__profile__position__type='MID', then=Value(3)),
                When(user__profile__position__type='ATT', then=Value(4)),
                default=Value(5),
                output_field=IntegerField(),
            )
        ).order_by(
            'position_order',
            'user__profile__player_number'
        )
        
        # Get pending invitations
        pending_invitations = TeamMember.objects.filter(
            team=team,
            is_active=False,
            invitation_token__isnull=False,
            invitation_accepted=False
        )
        
        log_error(
            request=request,
            error_message="Team members loaded",
            error_type="UserActivity",
            extra_context={
                "user_email": request.user.email,
                "user_id": request.user.id,
                "team_id": team.id,
                "team_name": team.name,
                "active_members_count": active_members.count(),
                "pending_invitations_count": pending_invitations.count(),
                "user_role": team_member.role,
                "user_is_admin": team_member.is_team_admin,
                "show_active_only": show_active_only,
                "members_by_position": {
                    "GK": active_members.filter(user__profile__position__type='GK').count(),
                    "DEF": active_members.filter(user__profile__position__type='DEF').count(),
                    "MID": active_members.filter(user__profile__position__type='MID').count(),
                    "ATT": active_members.filter(user__profile__position__type='ATT').count(),
                }
            }
        )
        
        context = {
            'team': team,
            'active_members': active_members,
            'pending_invitations': pending_invitations,
            'user': request.user,
            'user_is_admin': team_member.is_team_admin or team_member.role == TeamMember.Role.MANAGER,
            'show_active_only': show_active_only
        }
        return render(request, 'teams/team_members.html', context)
        
    except (Team.DoesNotExist, TeamMember.DoesNotExist) as e:
        log_error(
            request=request,
            error_message="Team members access denied",
            error_type="AuthorizationError",
            extra_context={
                "user_email": request.user.email,
                "user_id": request.user.id,
                "team_id": team_id,
                "error": str(e),
                "error_type": type(e).__name__
            }
        )
        messages.error(request, "You don't have access to this team.")
        return redirect('teams:team_list')
    except Exception as e:
        log_error(
            request=request,
            error_message=f"Failed to load team members: {str(e)}",
            error_type="SystemError",
            extra_context={
                "user_email": request.user.email,
                "user_id": request.user.id,
                "team_id": team_id,
                "error": str(e),
                "error_type": type(e).__name__,
                "traceback": traceback.format_exc()
            }
        )
        messages.error(request, "An error occurred while loading team members.")
        return redirect('teams:team_list')

@login_required
def invite_member(request, team_id):
    team = get_object_or_404(Team, id=team_id)
    team_member = get_object_or_404(TeamMember, team=team, user=request.user)
    
    if not team_member.is_team_admin and team_member.role != TeamMember.Role.MANAGER:
        return HttpResponseForbidden("You don't have permission to invite members.")

    if request.method == 'POST':
        form = TeamMemberInviteForm(team, request.POST)
        if form.is_valid():
            email = form.cleaned_data['email'].lower()
            role = form.cleaned_data['role']
            is_team_admin = form.cleaned_data['is_team_admin']
            is_official = form.cleaned_data['is_official']
            active_player = form.cleaned_data['active_player']
            
            # Generate invitation token
            token = secrets.token_urlsafe(32)
            
            # Create inactive team member
            team_member = TeamMember.objects.create(
                team=team,
                email=email,
                role=role,
                is_team_admin=is_team_admin,
                is_active=False,
                invitation_token=token
            )
            
            # Store is_official and active_player status in session for later use
            request.session[f'invite_{token}_is_official'] = is_official
            request.session[f'invite_{token}_active_player'] = active_player
            
            # Send invitation email
            invitation_url = request.build_absolute_uri(
                reverse('teams:register') + f'?token={token}'
            )
            send_invitation_email(email, team, invitation_url, role, is_team_admin, is_official)
            
            messages.success(request, f'Invitation sent to {email}')
            return redirect('teams:team_members', team_id=team.id)
    else:
        form = TeamMemberInviteForm(team)
    
    return render(request, 'teams/invite_member.html', {
        'form': form,
        'team': team
    })

@login_required
def toggle_team_admin(request, team_id, member_id):
    log_error(
        request=request,
        error_message="Team admin toggle initiated",
        error_type="UserActivity",
        extra_context={
            "user_email": request.user.email,
            "user_id": request.user.id,
            "team_id": team_id,
            "target_member_id": member_id,
            "path": request.path,
            "method": request.method
        }
    )
    
    try:
        team = get_object_or_404(Team, id=team_id)
        requesting_member = get_object_or_404(TeamMember, team=team, user=request.user, is_active=True)
        target_member = get_object_or_404(TeamMember, id=member_id, team=team, is_active=True)
        
        # Check if user has permission to modify team admin status
        if not (requesting_member.is_team_admin or requesting_member.role == TeamMember.Role.MANAGER):
            log_error(
                request=request,
                error_message="Unauthorized attempt to toggle team admin status",
                error_type="AuthorizationError",
                extra_context={
                    "user_email": request.user.email,
                    "user_id": request.user.id,
                    "team_id": team_id,
                    "target_member_id": member_id,
                    "user_role": requesting_member.role,
                    "is_admin": requesting_member.is_team_admin
                }
            )
            return HttpResponseForbidden("You don't have permission to modify team admin status.")
        
        # Log the state before change
        log_error(
            request=request,
            error_message="Team admin status before change",
            error_type="UserActivity",
            extra_context={
                "user_email": request.user.email,
                "user_id": request.user.id,
                "team_id": team_id,
                "team_name": team.name,
                "target_member_email": target_member.user.email,
                "target_member_id": member_id,
                "current_admin_status": target_member.is_team_admin
            }
        )
        
        target_member.is_team_admin = not target_member.is_team_admin
        target_member.save()
        
        # Log the successful change
        log_error(
            request=request,
            error_message="Team admin status changed successfully",
            error_type="UserActivity",
            extra_context={
                "user_email": request.user.email,
                "user_id": request.user.id,
                "team_id": team_id,
                "team_name": team.name,
                "target_member_email": target_member.user.email,
                "target_member_id": member_id,
                "new_admin_status": target_member.is_team_admin,
                "changed_by_role": requesting_member.role
            }
        )
        
        messages.success(
            request,
            f'{target_member.user.get_full_name()} is {"now" if target_member.is_team_admin else "no longer"} a team admin.'
        )
        return redirect('teams:team_members', team_id=team.id)
        
    except (Team.DoesNotExist, TeamMember.DoesNotExist) as e:
        log_error(
            request=request,
            error_message="Failed to toggle team admin - Invalid membership",
            error_type="AuthorizationError",
            extra_context={
                "user_email": request.user.email,
                "user_id": request.user.id,
                "team_id": team_id,
                "target_member_id": member_id,
                "error": str(e),
                "error_type": type(e).__name__
            }
        )
        messages.error(request, "Invalid team or member selection.")
        return redirect('teams:team_list')
    except Exception as e:
        log_error(
            request=request,
            error_message=f"Failed to toggle team admin status: {str(e)}",
            error_type="SystemError",
            extra_context={
                "user_email": request.user.email,
                "user_id": request.user.id,
                "team_id": team_id,
                "target_member_id": member_id,
                "error": str(e),
                "error_type": type(e).__name__,
                "traceback": traceback.format_exc()
            }
        )
        messages.error(request, "An error occurred while updating team admin status.")
        return redirect('teams:team_members', team_id=team_id)

@login_required
def remove_member(request, team_id, member_id):
    log_error(
        request=request,
        error_message="Member removal initiated",
        error_type="UserActivity",
        extra_context={
            "user_email": request.user.email,
            "user_id": request.user.id,
            "team_id": team_id,
            "target_member_id": member_id,
            "path": request.path,
            "method": request.method
        }
    )
    
    try:
        team = get_object_or_404(Team, id=team_id)
        requesting_member = get_object_or_404(TeamMember, team=team, user=request.user, is_active=True)
        target_member = get_object_or_404(TeamMember, id=member_id, team=team, is_active=True)
        
        # Check if user has permission to remove members
        if not (requesting_member.is_team_admin or requesting_member.role == TeamMember.Role.MANAGER):
            log_error(
                request=request,
                error_message="Unauthorized attempt to remove team member",
                error_type="AuthorizationError",
                extra_context={
                    "user_email": request.user.email,
                    "user_id": request.user.id,
                    "team_id": team_id,
                    "target_member_id": member_id,
                    "user_role": requesting_member.role,
                    "is_admin": requesting_member.is_team_admin
                }
            )
            return HttpResponseForbidden("You don't have permission to remove team members.")
        
        # Don't allow removing yourself
        if target_member.user == request.user:
            log_error(
                request=request,
                error_message="Attempted to remove self from team",
                error_type="ValidationError",
                extra_context={
                    "user_email": request.user.email,
                    "user_id": request.user.id,
                    "team_id": team_id,
                    "team_name": team.name
                }
            )
            messages.error(request, "You cannot remove yourself from the team.")
            return redirect('teams:team_members', team_id=team.id)
        
        # Log member details before removal
        log_error(
            request=request,
            error_message="Member details before removal",
            error_type="UserActivity",
            extra_context={
                "user_email": request.user.email,
                "user_id": request.user.id,
                "team_id": team_id,
                "team_name": team.name,
                "target_member_email": target_member.user.email,
                "target_member_id": member_id,
                "target_member_role": target_member.role,
                "target_member_is_admin": target_member.is_team_admin
            }
        )
        
        # Clear member data and set as inactive
        target_member.is_active = False
        target_member.invitation_accepted = False
        target_member.invitation_token = None
        target_member.is_team_admin = False
        target_member.save()
        
        # Log successful removal
        log_error(
            request=request,
            error_message="Member removed successfully",
            error_type="UserActivity",
            extra_context={
                "user_email": request.user.email,
                "user_id": request.user.id,
                "team_id": team_id,
                "team_name": team.name,
                "target_member_email": target_member.user.email,
                "target_member_id": member_id,
                "removed_by_role": requesting_member.role
            }
        )
        
        messages.success(request, f'{target_member.user.get_full_name()} has been removed from the team.')
        return redirect('teams:team_members', team_id=team.id)
        
    except (Team.DoesNotExist, TeamMember.DoesNotExist) as e:
        log_error(
            request=request,
            error_message="Failed to remove member - Invalid membership",
            error_type="AuthorizationError",
            extra_context={
                "user_email": request.user.email,
                "user_id": request.user.id,
                "team_id": team_id,
                "target_member_id": member_id,
                "error": str(e),
                "error_type": type(e).__name__
            }
        )
        messages.error(request, "Invalid team or member selection.")
        return redirect('teams:team_list')
    except Exception as e:
        log_error(
            request=request,
            error_message=f"Failed to remove team member: {str(e)}",
            error_type="SystemError",
            extra_context={
                "user_email": request.user.email,
                "user_id": request.user.id,
                "team_id": team_id,
                "target_member_id": member_id,
                "error": str(e),
                "error_type": type(e).__name__,
                "traceback": traceback.format_exc()
            }
        )
        messages.error(request, "An error occurred while removing the team member.")
        return redirect('teams:team_members', team_id=team_id)

@login_required
def remove_pending_invitation(request, team_id, member_id):
    team = get_object_or_404(Team, id=team_id)
    requesting_member = get_object_or_404(TeamMember, team=team, user=request.user, is_active=True)
    pending_member = get_object_or_404(TeamMember, id=member_id, team=team, is_active=False)
    
    # Check if user has permission to remove members
    if not (requesting_member.is_team_admin or requesting_member.role == TeamMember.Role.MANAGER):
        return HttpResponseForbidden("You don't have permission to remove invitations.")
    
    # Delete the pending invitation
    pending_member.delete()
    
    messages.success(request, f'Invitation to {pending_member.email} has been cancelled.')
    return redirect('teams:team_members', team_id=team.id)

def register(request):
    token = request.GET.get('token')
    try:
        team_member = TeamMember.objects.get(invitation_token=token, is_active=False)
    except TeamMember.DoesNotExist:
        log_error(
            request=request,
            error_message="Invalid or expired invitation token",
            error_type="RegistrationError",
            extra_context={"token": token}
        )
        context = {
            'title': 'Invalid Invitation',
            'message': 'This invitation link is no longer active or has already been used.',
            'help_text': 'Please contact your team administrator for a new invitation.'
        }
        return render(request, 'teams/404.html', context, status=404)
    
    if request.method == 'POST':
        # Remove sensitive data from logs
        safe_post_data = request.POST.copy()
        if 'password1' in safe_post_data:
            safe_post_data['password1'] = '***'
        if 'password2' in safe_post_data:
            safe_post_data['password2'] = '***'
            
        log_error(
            request=request,
            error_message="Registration POST request received",
            error_type="RegistrationDebug",
            extra_context={
                "post_data": dict(safe_post_data),
                "files": bool(request.FILES),
                "team_member_data": {
                    "email": team_member.email,
                    "team": team_member.team.name,
                    "role": team_member.role
                }
            }
        )
        
        form = UserRegistrationForm(request.POST, request.FILES, email=team_member.email)
        if form.is_valid():
            # Remove sensitive data from cleaned_data logs
            safe_cleaned_data = form.cleaned_data.copy()
            if 'password1' in safe_cleaned_data:
                safe_cleaned_data['password1'] = '***'
            if 'password2' in safe_cleaned_data:
                safe_cleaned_data['password2'] = '***'
                
            log_error(
                request=request,
                error_message="Form validation successful",
                error_type="RegistrationDebug",
                extra_context={"cleaned_data": safe_cleaned_data}
            )
            try:
                with transaction.atomic():
                    # Try to get existing user or create new one
                    user = User.objects.filter(email=team_member.email).first()
                    if user:
                        # Update existing user
                        user.first_name = form.cleaned_data['first_name']
                        user.last_name = form.cleaned_data['last_name']
                        user.date_of_birth = form.cleaned_data['date_of_birth']
                        user.save()
                        log_error(
                            request=request,
                            error_message="Updated existing user",
                            error_type="RegistrationDebug",
                            extra_context={
                                "user_id": user.id,
                                "email": user.email
                            }
                        )
                    else:
                        # Create new user
                        user = form.save()
                        log_error(
                            request=request,
                            error_message="Created new user",
                            error_type="RegistrationDebug",
                            extra_context={
                                "user_id": user.id,
                                "email": user.email
                            }
                        )

                    # Get the is_official status from session
                    is_official = request.session.get(f'invite_{token}_is_official', False)
                    active_player = request.session.get(f'invite_{token}_active_player', True)
                    
                    # Check if profile exists
                    profile_exists = hasattr(user, 'profile')
                    log_error(
                        request=request,
                        error_message="Profile check",
                        error_type="RegistrationDebug",
                        extra_context={
                            "profile_exists": profile_exists,
                            "user_id": user.id
                        }
                    )
                    
                    # Create or update profile
                    profile = Profile.objects.get_or_create(user=user)[0]
                    
                    # Log profile state before update
                    log_error(
                        request=request,
                        error_message="Profile state before update",
                        error_type="RegistrationDebug",
                        extra_context={
                            "profile_id": profile.id,
                            "initial_state": {
                                "player_number": profile.player_number,
                                "position": str(profile.position) if profile.position else None,
                                "is_official": profile.is_official,
                                "active_player": profile.active_player,
                                "level": profile.level,
                                "rut": profile.rut,
                                "country": profile.country,
                                "description": profile.description
                            }
                        }
                    )
                    
                    # Save all profile fields
                    profile_fields = {
                        'player_number': form.cleaned_data['player_number'],
                        'position': form.cleaned_data['position'],
                        'is_official': is_official,
                        'active_player': active_player,
                        'date_of_birth': form.cleaned_data['date_of_birth'],
                        'level': form.cleaned_data['level'],
                        'rut': form.cleaned_data['rut'],
                        'country': form.cleaned_data['country'],
                        'description': form.cleaned_data['description']
                    }
                    
                    # Log profile data before save
                    log_error(
                        request=request,
                        error_message="Profile data before save",
                        error_type="RegistrationDebug",
                        extra_context={"profile_data": profile_fields}
                    )
                    
                    # Update all fields at once
                    for field, value in profile_fields.items():
                        setattr(profile, field, value)
                        # Log each field update
                        log_error(
                            request=request,
                            error_message=f"Setting profile field: {field}",
                            error_type="RegistrationDebug",
                            extra_context={
                                "field": field,
                                "value": str(value),
                                "profile_id": profile.id
                            }
                        )
                    
                    # Save the profile
                    profile.save()
                    
                    # Force refresh from database
                    profile.refresh_from_db()
                    
                    # Verify profile was saved correctly
                    saved_profile = Profile.objects.get(user=user)
                    log_error(
                        request=request,
                        error_message="Profile data after save",
                        error_type="RegistrationDebug",
                        extra_context={
                            "saved_profile_data": {
                                "player_number": saved_profile.player_number,
                                "position": str(saved_profile.position),
                                "is_official": saved_profile.is_official,
                                "date_of_birth": str(saved_profile.date_of_birth),
                                "level": saved_profile.level,
                                "rut": saved_profile.rut,
                                "country": saved_profile.country,
                                "description": saved_profile.description
                            }
                        }
                    )

                    # Update team member
                    team_member.user = user
                    team_member.is_active = True
                    team_member.invitation_accepted = True
                    team_member.save()
                    
                    log_error(
                        request=request,
                        error_message="Team member updated",
                        error_type="RegistrationDebug",
                        extra_context={
                            "team_member_data": {
                                "id": team_member.id,
                                "user_id": team_member.user_id,
                                "team": team_member.team.name,
                                "is_active": team_member.is_active,
                                "invitation_accepted": team_member.invitation_accepted
                            }
                        }
                    )

                    # Clean up the session
                    request.session.pop(f'invite_{token}_is_official', None)

                    # Log in the user
                    login(request, user)
                    messages.success(request, f'Registration successful! You are now a member of {team_member.team.name}.')
                    return redirect('teams:dashboard')

            except Exception as e:
                log_error(
                    request=request,
                    error_message=f"Registration failed: {str(e)}",
                    error_type="RegistrationError",
                    extra_context={
                        "team_id": team_member.team.id,
                        "email": team_member.email,
                        "role": team_member.role,
                        "is_team_admin": team_member.is_team_admin,
                        "form_data": form.cleaned_data,
                        "error": str(e),
                        "error_type": type(e).__name__
                    }
                )
                messages.error(request, 'An error occurred during registration. Please try again.')
        else:
            log_error(
                request=request,
                error_message="Form validation failed",
                error_type="RegistrationError",
                extra_context={
                    "form_errors": form.errors,
                    "non_field_errors": form.non_field_errors()
                }
            )
            if settings.DEBUG:
                messages.error(request, 'Please correct the errors below.')
    else:
        # Pre-fill data if user exists
        user = User.objects.filter(email=team_member.email).first()
        initial_data = {'email': team_member.email}
        if user:
            initial_data.update({
                'first_name': user.first_name,
                'last_name': user.last_name,
            })
        form = UserRegistrationForm(initial=initial_data, email=team_member.email)
    
    # Get the is_official status for the template
    is_official = request.session.get(f'invite_{token}_is_official', False)
    
    return render(request, 'teams/register.html', {
        'form': form,
        'is_official': is_official,
        'team': team_member.team
    })

@user_passes_test(is_admin)
def admin_teams(request):
    teams = Team.objects.all().order_by('name')
    return render(request, 'teams/admin_teams.html', {'teams': teams})

@user_passes_test(is_admin)
def create_team(request):
    if request.method == 'POST':
        form = TeamForm(request.POST)
        if form.is_valid():
            team = form.save()
            messages.success(request, f'Team "{team.name}" has been created successfully!')
            return redirect('teams:admin_teams')
    else:
        form = TeamForm()
    
    return render(request, 'teams/create_team.html', {'form': form})

@user_passes_test(is_admin)
def delete_team(request, team_id):
    team = get_object_or_404(Team, id=team_id)
    if request.method == 'POST':
        team.delete()
        messages.success(request, f'Team "{team.name}" has been deleted successfully!')
        return redirect('teams:admin_teams')
    return render(request, 'teams/delete_team.html', {'team': team})

@login_required
def edit_team(request, team_id):
    team = get_object_or_404(Team, id=team_id)
    # Check if user is a manager of this team
    try:
        team_member = TeamMember.objects.get(
            team=team,
            user=request.user,
            role=TeamMember.Role.MANAGER,
            is_active=True
        )
    except TeamMember.DoesNotExist:
        return HttpResponseForbidden("You don't have permission to edit this team.")
    
    if request.method == 'POST':
        form = TeamForm(request.POST, instance=team)
        if form.is_valid():
            form.save()
            messages.success(request, f'Team "{team.name}" has been updated successfully!')
            return redirect('teams:dashboard')
    else:
        form = TeamForm(instance=team)
    
    return render(request, 'teams/edit_team.html', {
        'form': form,
        'team': team
    })

@login_required
def add_team_member(request, team_id):
    team = get_object_or_404(Team, id=team_id)
    requesting_member = get_object_or_404(TeamMember, team=team, user=request.user, is_active=True)
    
    # Check if user has permission to add members
    if not (requesting_member.is_team_admin or requesting_member.role == TeamMember.Role.MANAGER):
        return HttpResponseForbidden("You don't have permission to add team members.")
    
    if request.method == 'POST':
        form = AddTeamMemberForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    # Create the user
                    user = form.save()
                    
                    # Create the team member
                    TeamMember.objects.create(
                        user=user,
                        team=team,
                        role=form.cleaned_data['role'],
                        is_team_admin=form.cleaned_data['is_team_admin'],
                        is_active=True,
                        invitation_accepted=True
                    )
                    
                    messages.success(request, f'{user.get_full_name()} has been added to the team.')
                    return redirect('teams:team_members', team_id=team.id)
            except Exception as e:
                messages.error(request, f'Error creating user: {str(e)}')
    else:
        form = AddTeamMemberForm()
    
    return render(request, 'teams/add_team_member.html', {
        'form': form,
        'team': team
    })

@login_required
def edit_profile(request):
    if request.method == 'POST':
        form = UserProfileForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            try:
                user = form.save(commit=False)
                profile = Profile.objects.get_or_create(user=user)[0]
                
                # Handle profile picture upload
                if form.cleaned_data.get('profile_picture'):
                    # Validate file size
                    file = form.cleaned_data['profile_picture']
                    if file.size > 2 * 1024 * 1024:  # 2MB limit
                        log_upload_error(
                            request=request,
                            file=file,
                            error_message="File size exceeds maximum limit of 2MB",
                            upload_type="profile_picture",
                            attempted_location="profile_pics/",
                            validation_errors={
                                "size_limit": "2MB",
                                "actual_size": f"{file.size / (1024 * 1024):.2f}MB"
                            }
                        )
                        messages.error(request, 'Profile picture must be less than 2MB')
                        return render(request, 'teams/edit_profile.html', {'form': form})
                    
                    # Validate file type using file extension
                    allowed_extensions = ['.jpg', '.jpeg', '.png']
                    file_extension = os.path.splitext(file.name)[1].lower()
                    if file_extension not in allowed_extensions:
                        log_upload_error(
                            request=request,
                            file=file,
                            error_message="Invalid file type",
                            upload_type="profile_picture",
                            attempted_location="profile_pics/",
                            validation_errors={
                                "allowed_extensions": allowed_extensions,
                                "actual_extension": file_extension
                            }
                        )
                        messages.error(request, 'Profile picture must be JPEG or PNG')
                        return render(request, 'teams/edit_profile.html', {'form': form})
                    
                    profile.profile_picture = file
                
                # Save user and profile
                user.save()
                profile.player_number = form.cleaned_data['player_number']
                profile.position = form.cleaned_data['position']
                profile.level = form.cleaned_data['level']
                profile.rut = form.cleaned_data['rut']
                profile.country = form.cleaned_data['country']
                profile.date_of_birth = form.cleaned_data['date_of_birth']
                profile.description = form.cleaned_data['description']
                profile.save()
                
                messages.success(request, 'Profile updated successfully')
                return redirect('teams:dashboard')
            except Exception as e:
                log_upload_error(
                    request=request,
                    file=form.cleaned_data.get('profile_picture'),
                    error_message=str(e),
                    upload_type="profile_picture",
                    attempted_location="profile_pics/",
                    validation_errors={"unexpected_error": str(e)}
                )
                messages.error(request, 'An error occurred while updating your profile')
                return render(request, 'teams/edit_profile.html', {'form': form})
        else:
            if 'profile_picture' in form.errors:
                log_upload_error(
                    request=request,
                    file=request.FILES.get('profile_picture'),
                    error_message=form.errors['profile_picture'],
                    upload_type="profile_picture",
                    attempted_location="profile_pics/",
                    validation_errors={"form_errors": form.errors['profile_picture']}
                )
    else:
        form = UserProfileForm(instance=request.user)
    
    return render(request, 'teams/edit_profile.html', {'form': form})

@login_required
def view_profile(request, user_id):
    user = get_object_or_404(User, id=user_id)
    profile = getattr(user, 'profile', None)
    
    # Check if the requesting user is in any team with the target user
    common_teams = Team.objects.filter(
        teammember__user=request.user,
        teammember__is_active=True
    ).filter(
        teammember__user=user,
        teammember__is_active=True
    ).distinct()
    
    if not common_teams.exists():
        return HttpResponseForbidden("You don't have permission to view this profile.")
    
    context = {
        'profile_user': user,
        'profile': profile,
        'common_teams': common_teams,
    }
    return render(request, 'teams/view_profile.html', context)

@login_required
def season_list(request, team_id):
    team = get_object_or_404(Team, id=team_id)
    team_member = get_object_or_404(TeamMember, team=team, user=request.user, is_active=True)
    
    seasons = Season.objects.filter(team=team).order_by('-start_date')
    current_season = seasons.filter(is_active=True).first()
    
    context = {
        'team': team,
        'seasons': seasons,
        'current_season': current_season,
        'is_admin': team_member.is_team_admin or team_member.role == TeamMember.Role.MANAGER
    }
    return render(request, 'teams/season_list.html', context)

@login_required
def season_create(request, team_id):
    team = get_object_or_404(Team, id=team_id)
    team_member = get_object_or_404(TeamMember, team=team, user=request.user, is_active=True)
    
    if not (team_member.is_team_admin or team_member.role == TeamMember.Role.MANAGER):
        return HttpResponseForbidden("You don't have permission to create seasons.")
    
    if request.method == 'POST':
        form = SeasonForm(request.POST)
        if form.is_valid():
            season = form.save(commit=False)
            season.team = team
            season.save()
            messages.success(request, f'Season "{season.name}" has been created.')
            return redirect('teams:season_detail', team_id=team.id, season_id=season.id)
    else:
        form = SeasonForm()
    
    return render(request, 'teams/season_form.html', {
        'form': form,
        'team': team,
        'title': 'Create Season'
    })

@login_required
def season_edit(request, team_id, season_id):
    team = get_object_or_404(Team, id=team_id)
    season = get_object_or_404(Season, id=season_id, team=team)
    team_member = get_object_or_404(TeamMember, team=team, user=request.user, is_active=True)
    
    if not (team_member.is_team_admin or team_member.role == TeamMember.Role.MANAGER):
        return HttpResponseForbidden("You don't have permission to edit seasons.")
    
    if request.method == 'POST':
        form = SeasonForm(request.POST, instance=season)
        if form.is_valid():
            form.save()
            messages.success(request, f'Season "{season.name}" has been updated.')
            return redirect('teams:season_detail', team_id=team.id, season_id=season.id)
    else:
        form = SeasonForm(instance=season)
    
    return render(request, 'teams/season_form.html', {
        'form': form,
        'team': team,
        'season': season,
        'title': 'Edit Season'
    })

@login_required
def season_detail(request, team_id, season_id):
    team = get_object_or_404(Team, id=team_id)
    season = get_object_or_404(Season, id=season_id, team=team)
    team_member = get_object_or_404(TeamMember, team=team, user=request.user, is_active=True)
    
    matches = Match.objects.filter(season=season).order_by('match_date', 'match_time')
    upcoming_matches = matches.filter(
        match_date__gte=timezone.now().date()
    )
    past_matches = matches.exclude(
        id__in=upcoming_matches.values_list('id', flat=True)
    )
    
    context = {
        'team': team,
        'season': season,
        'upcoming_matches': upcoming_matches,
        'past_matches': past_matches,
        'is_admin': team_member.is_team_admin or team_member.role == TeamMember.Role.MANAGER
    }
    return render(request, 'teams/season_detail.html', context)

@login_required
def match_create(request, team_id, season_id):
    team = get_object_or_404(Team, id=team_id)
    season = get_object_or_404(Season, id=season_id, team=team)
    team_member = get_object_or_404(TeamMember, team=team, user=request.user, is_active=True)
    
    if not (team_member.is_team_admin or team_member.role == TeamMember.Role.MANAGER):
        log_error(
            request=request,
            error_message="Unauthorized attempt to create match",
            error_type="PermissionError",
            extra_context={
                "team_id": team_id,
                "season_id": season_id,
                "user_role": team_member.role,
                "is_admin": team_member.is_team_admin
            }
        )
        return HttpResponseForbidden("You don't have permission to create matches.")
    
    if request.method == 'POST':
        form = MatchForm(request.POST, season=season)
        if form.is_valid():
            try:
                match = form.save(commit=False)
                match.season = season
                match.save()
                messages.success(request, f'Match against {match.opponent} has been scheduled.')
                return redirect('teams:season_detail', team_id=team.id, season_id=season.id)
            except Exception as e:
                log_error(
                    request=request,
                    error_message=f"Failed to create match: {str(e)}",
                    error_type="MatchCreationError",
                    extra_context={
                        "team_id": team_id,
                        "season_id": season_id,
                        "opponent": form.cleaned_data.get('opponent'),
                        "match_date": form.cleaned_data.get('match_date'),
                        "match_time": form.cleaned_data.get('match_time')
                    }
                )
                messages.error(request, 'An error occurred while scheduling the match.')
                return render(request, 'teams/match_form.html', {
                    'form': form,
                    'team': team,
                    'season': season,
                    'title': 'Schedule Match'
                })
    else:
        form = MatchForm(season=season)
    
    return render(request, 'teams/match_form.html', {
        'form': form,
        'team': team,
        'season': season,
        'title': 'Schedule Match'
    })

@login_required
def match_edit(request, team_id, season_id, match_id):
    team = get_object_or_404(Team, id=team_id)
    season = get_object_or_404(Season, id=season_id, team=team)
    match = get_object_or_404(Match, id=match_id, season=season)
    team_member = get_object_or_404(TeamMember, team=team, user=request.user, is_active=True)
    
    if not (team_member.is_team_admin or team_member.role == TeamMember.Role.MANAGER):
        return HttpResponseForbidden("You don't have permission to edit matches.")
    
    if request.method == 'POST':
        form = MatchForm(request.POST, instance=match, season=season)
        if form.is_valid():
            form.save()
            messages.success(request, f'Match against {match.opponent} has been updated.')
            return redirect('teams:season_detail', team_id=team.id, season_id=season.id)
    else:
        form = MatchForm(instance=match, season=season)
    
    return render(request, 'teams/match_form.html', {
        'form': form,
        'team': team,
        'season': season,
        'match': match,
        'title': 'Edit Match'
    })

@login_required
def edit_member(request, team_id, user_id):
    team = get_object_or_404(Team, id=team_id)
    member_to_edit = get_object_or_404(User, id=user_id)
    team_member = get_object_or_404(TeamMember, team=team, user=member_to_edit)
    
    # Log access attempt
    log_error(
        request=request,
        error_message="Member edit page access",
        error_type="UserActivity",
        extra_context={
            "user_email": request.user.email,
            "admin_user_id": request.user.id,
            "member_email": member_to_edit.email,
            "member_id": member_to_edit.id,
            "team_id": team.id,
            "team_name": team.name,
            "path": request.path,
            "method": request.method
        }
    )
    
    # Check if the requesting user is a team admin
    requester_member = get_object_or_404(TeamMember, team=team, user=request.user)
    if not requester_member.is_team_admin:
        log_error(
            request=request,
            error_message="Unauthorized member edit attempt",
            error_type="AuthorizationError",
            extra_context={
                "user_email": request.user.email,
                "user_id": request.user.id,
                "team_id": team.id,
                "attempted_member_id": user_id
            }
        )
        return HttpResponseForbidden("You don't have permission to edit member profiles.")
    
    if request.method == 'POST':
        form = AdminMemberProfileForm(request.POST, request.FILES, instance=member_to_edit)
        if form.is_valid():
            try:
                with transaction.atomic():
                    # Log form data (excluding sensitive fields)
                    log_error(
                        request=request,
                        error_message="Member profile update initiated",
                        error_type="ProfileUpdate",
                        extra_context={
                            "user_email": request.user.email,
                            "admin_user_id": request.user.id,
                            "member_email": member_to_edit.email,
                            "member_id": member_to_edit.id,
                            "team_id": team.id,
                            "form_fields": {
                                "player_number": form.cleaned_data['player_number'],
                                "position": str(form.cleaned_data['position']),
                                "level": form.cleaned_data['level'],
                                "is_official": form.cleaned_data['is_official'],
                                "active_player": form.cleaned_data['active_player'],
                                "country": form.cleaned_data['country'],
                                "has_new_picture": bool(form.cleaned_data.get('profile_picture')),
                                "picture_cleared": bool(request.POST.get('profile_picture-clear'))
                            }
                        }
                    )
                    
                    user = form.save(commit=False)
                    user.save()
                    
                    # Get or create profile
                    profile = Profile.objects.get_or_create(user=user)[0]
                    
                    # Handle profile picture
                    if form.cleaned_data.get('profile_picture'):
                        # Validate file size
                        file = form.cleaned_data['profile_picture']
                        if file.size > 2 * 1024 * 1024:  # 2MB limit
                            log_error(
                                request=request,
                                error_message="Profile picture size validation failed",
                                error_type="FileValidationError",
                                extra_context={
                                    "user_email": request.user.email,
                                    "member_email": member_to_edit.email,
                                    "file_size": file.size,
                                    "max_size": 2 * 1024 * 1024
                                }
                            )
                            messages.error(request, 'Profile picture must be less than 2MB')
                            return render(request, 'teams/edit_member.html', {'form': form, 'team': team, 'member': member_to_edit})
                        
                        # Validate file type
                        allowed_extensions = ['.jpg', '.jpeg', '.png']
                        file_extension = os.path.splitext(file.name)[1].lower()
                        if file_extension not in allowed_extensions:
                            log_error(
                                request=request,
                                error_message="Invalid profile picture format",
                                error_type="FileValidationError",
                                extra_context={
                                    "user_email": request.user.email,
                                    "member_email": member_to_edit.email,
                                    "file_extension": file_extension,
                                    "allowed_extensions": allowed_extensions
                                }
                            )
                            messages.error(request, 'Profile picture must be JPEG or PNG')
                            return render(request, 'teams/edit_member.html', {'form': form, 'team': team, 'member': member_to_edit})
                        
                        profile.profile_picture = file
                        
                        # Log successful file upload
                        log_error(
                            request=request,
                            error_message="Profile picture uploaded successfully",
                            error_type="FileOperation",
                            extra_context={
                                "user_email": request.user.email,
                                "member_email": member_to_edit.email,
                                "file_name": file.name,
                                "file_size": file.size
                            }
                        )
                    elif request.POST.get('profile_picture-clear'):
                        profile.profile_picture = 'profile_pics/castolo.png'  # Reset to default
                        log_error(
                            request=request,
                            error_message="Profile picture reset to default",
                            error_type="FileOperation",
                            extra_context={
                                "user_email": request.user.email,
                                "member_email": member_to_edit.email,
                                "default_picture": 'profile_pics/castolo.png'
                            }
                        )
                    
                    # Save all profile fields
                    profile.player_number = form.cleaned_data['player_number']
                    profile.position = form.cleaned_data['position']
                    profile.level = form.cleaned_data['level']
                    profile.is_official = form.cleaned_data['is_official']
                    profile.active_player = form.cleaned_data['active_player']
                    profile.rut = form.cleaned_data['rut']
                    profile.country = form.cleaned_data['country']
                    profile.date_of_birth = form.cleaned_data['date_of_birth']
                    profile.description = form.cleaned_data['description']
                    profile.save()
                    
                    # Log successful profile update
                    log_error(
                        request=request,
                        error_message="Member profile updated successfully",
                        error_type="ProfileUpdate",
                        extra_context={
                            "user_email": request.user.email,
                            "admin_user_id": request.user.id,
                            "member_email": member_to_edit.email,
                            "member_id": member_to_edit.id,
                            "team_id": team.id,
                            "updated_fields": {
                                "player_number": profile.player_number,
                                "position": str(profile.position),
                                "level": profile.level,
                                "is_official": profile.is_official,
                                "active_player": profile.active_player,
                                "country": profile.country,
                                "has_profile_picture": bool(profile.profile_picture)
                            }
                        }
                    )
                    
                    messages.success(request, f"{member_to_edit.get_full_name()}'s profile has been updated successfully!")
                    return redirect('teams:dashboard')
            except Exception as e:
                log_error(
                    request=request,
                    error_message=f"Failed to update member profile: {str(e)}",
                    error_type="ProfileUpdateError",
                    extra_context={
                        "user_email": request.user.email,
                        "admin_user_id": request.user.id,
                        "member_email": member_to_edit.email,
                        "member_id": member_to_edit.id,
                        "team_id": team_id,
                        "error": str(e),
                        "error_type": type(e).__name__,
                        "traceback": traceback.format_exc()
                    }
                )
                messages.error(request, 'An error occurred while updating the profile.')
                return render(request, 'teams/edit_member.html', {'form': form, 'team': team, 'member': member_to_edit})
    else:
        form = AdminMemberProfileForm(instance=member_to_edit)
    
    return render(request, 'teams/edit_member.html', {
        'form': form,
        'team': team,
        'member': member_to_edit
    })

@login_required
def payment_list(request, team_id, season_id):
    team = get_object_or_404(Team, id=team_id)
    season = get_object_or_404(Season, id=season_id)
    if not request.user.is_superuser and not TeamMember.objects.filter(team=team, user=request.user, is_team_admin=True).exists():
        return HttpResponseForbidden("You don't have permission to manage payments.")
    
    payments = Payment.objects.filter(season=season)
    return render(request, 'teams/payment_list.html', {
        'team': team,
        'season': season,
        'payments': payments,
    })

@login_required
def payment_create(request, team_id, season_id):
    team = get_object_or_404(Team, id=team_id)
    season = get_object_or_404(Season, id=season_id)
    
    if not request.user.is_superuser and not TeamMember.objects.filter(team=team, user=request.user, is_team_admin=True).exists():
        log_error(
            request=request,
            error_message="Unauthorized attempt to create payment",
            error_type="PermissionError",
            extra_context={
                "team_id": team_id,
                "season_id": season_id
            }
        )
        return HttpResponseForbidden("You don't have permission to create payments.")

    if request.method == 'POST':
        form = PaymentForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    payment = form.save(commit=False)
                    payment.season = season
                    payment.save()
                    
                    # Create player payments
                    official_players = TeamMember.objects.filter(
                        team=team,
                        role=TeamMember.Role.PLAYER,
                        user__profile__is_official=True,
                        is_active=True
                    )
                    
                    for player in official_players:
                        PlayerPayment.objects.create(
                            payment=payment,
                            player=player,
                            amount=0
                        )
                    
                    messages.success(request, 'Payment created successfully.')
                    return redirect('teams:payment_edit', team_id=team.id, season_id=season.id, payment_id=payment.id)
            except Exception as e:
                log_error(
                    request=request,
                    error_message=f"Failed to create payment: {str(e)}",
                    error_type="PaymentCreationError",
                    extra_context={
                        "team_id": team_id,
                        "season_id": season_id,
                        "form_data": form.cleaned_data
                    }
                )
                messages.error(request, 'An error occurred while creating the payment.')
                return render(request, 'teams/payment_form.html', {'form': form, 'team': team, 'season': season})
    else:
        form = PaymentForm()
    
    return render(request, 'teams/payment_form.html', {
        'form': form,
        'team': team,
        'season': season,
        'title': 'Create Payment'
    })

@login_required
def payment_edit(request, team_id, season_id, payment_id):
    team = get_object_or_404(Team, id=team_id)
    season = get_object_or_404(Season, id=season_id)
    payment = get_object_or_404(Payment, id=payment_id, season=season)
    
    if not request.user.is_superuser and not TeamMember.objects.filter(team=team, user=request.user, is_team_admin=True).exists():
        return HttpResponseForbidden("You don't have permission to edit payments.")

    if request.method == 'POST':
        form = PaymentForm(request.POST, instance=payment)
        formset = PlayerPaymentFormSet(request.POST, instance=payment)
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                form.save()
                formset.save()  # Save the formset changes
            messages.success(request, 'Payment updated successfully.')
            return redirect('teams:payment_list', team_id=team.id, season_id=season.id)
    else:
        form = PaymentForm(instance=payment)
        formset = PlayerPaymentFormSet(instance=payment)
    
    return render(request, 'teams/payment_form.html', {
        'form': form,
        'formset': formset,
        'team': team,
        'season': season,
        'payment': payment,
        'title': 'Edit Payment'
    })

@login_required
def payment_delete(request, team_id, season_id, payment_id):
    team = get_object_or_404(Team, id=team_id)
    season = get_object_or_404(Season, id=season_id)
    payment = get_object_or_404(Payment, id=payment_id, season=season)
    
    if not request.user.is_superuser and not TeamMember.objects.filter(team=team, user=request.user, is_team_admin=True).exists():
        return HttpResponseForbidden("You don't have permission to delete payments.")

    if request.method == 'POST':
        payment.delete()
        messages.success(request, 'Payment deleted successfully.')
        return redirect('teams:payment_list', team_id=team.id, season_id=season.id)
    
    return render(request, 'teams/payment_delete.html', {
        'team': team,
        'season': season,
        'payment': payment,
    })

@login_required
def toggle_player_payment(request, team_id, season_id, payment_id, player_payment_id):
    if request.method == 'POST':
        team = get_object_or_404(Team, id=team_id)
        player_payment = get_object_or_404(PlayerPayment, id=player_payment_id)
        is_admin = request.headers.get('X-Admin-Action') == 'true'
        
        # Check permissions
        if is_admin and not (request.user.is_superuser or TeamMember.objects.filter(team=team, user=request.user, is_team_admin=True).exists()):
            return HttpResponseForbidden("You don't have permission to verify payments.")
            
        # Check if the user is the player or an admin
        is_player = TeamMember.objects.filter(team=team, user=request.user, id=player_payment.player.id).exists()
        if not (is_admin or is_player):
            return HttpResponseForbidden("You don't have permission to manage this payment.")

        # Handle admin actions
        if is_admin:
            if player_payment.is_paid and not player_payment.admin_verified:
                # Admin verifying a payment
                player_payment.mark_as_paid(is_admin=True)
            elif not player_payment.is_paid:
                # Admin marking as paid
                player_payment.mark_as_paid(is_admin=True)
            else:
                # Admin unmarking a verified payment
                player_payment.mark_as_unpaid(is_admin=True)
        # Handle player actions
        else:
            if player_payment.admin_verified:
                return HttpResponseForbidden("This payment has been verified by an admin and cannot be modified.")
            
            if player_payment.is_paid:
                # Player canceling their payment notification
                player_payment.mark_as_unpaid()
            else:
                # Player marking as paid (pending approval)
                player_payment.mark_as_paid()
        
        return JsonResponse({
            'status': 'success',
            'is_paid': player_payment.is_paid,
            'admin_verified': player_payment.admin_verified,
            'paid_at': player_payment.paid_at.strftime('%Y-%m-%d %H:%M') if player_payment.paid_at else None
        })
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'})

@login_required
def team_list(request):
    """View for listing and selecting teams."""
    log_error(
        request=request,
        error_message="Team list page access",
        error_type="UserActivity",
        extra_context={
            "user_email": request.user.email,
            "user_id": request.user.id,
            "path": request.path,
            "method": request.method
        }
    )
    
    try:
        team_memberships = TeamMember.objects.filter(
            user=request.user,
            is_active=True
        ).select_related('team')
        
        log_error(
            request=request,
            error_message="Team list loaded",
            error_type="UserActivity",
            extra_context={
                "user_email": request.user.email,
                "user_id": request.user.id,
                "teams_count": team_memberships.count(),
                "teams": [
                    {
                        "team_id": tm.team.id,
                        "team_name": tm.team.name,
                        "role": tm.role,
                        "is_admin": tm.is_team_admin
                    }
                    for tm in team_memberships
                ]
            }
        )
        
        return render(request, 'teams/team_list.html', {
            'team_memberships': team_memberships
        })
    except Exception as e:
        log_error(
            request=request,
            error_message=f"Failed to load team list: {str(e)}",
            error_type="SystemError",
            extra_context={
                "user_email": request.user.email,
                "user_id": request.user.id,
                "error": str(e),
                "error_type": type(e).__name__,
                "traceback": traceback.format_exc()
            }
        )
        messages.error(request, "An error occurred while loading your teams.")
        return redirect('teams:dashboard')

@login_required
def refresh_players(request, team_id, season_id, payment_id):
    team = get_object_or_404(Team, id=team_id)
    season = get_object_or_404(Season, id=season_id)
    payment = get_object_or_404(Payment, id=payment_id, season=season)
    
    if not request.user.is_superuser and not TeamMember.objects.filter(team=team, user=request.user, is_team_admin=True).exists():
        return HttpResponseForbidden("You don't have permission to refresh payments.")

    # Get all current official players
    official_players = TeamMember.objects.filter(
        team=team,
        role=TeamMember.Role.PLAYER,
        user__profile__is_official=True,
        is_active=True
    )
    
    # Get existing player payments
    existing_player_payments = {pp.player_id: pp for pp in payment.player_payments.all()}
    
    # Create new player payments for players who don't have one
    new_players = 0
    for player in official_players:
        if player.id not in existing_player_payments:
            PlayerPayment.objects.create(
                payment=payment,
                player=player,
                amount=0  # Default amount
            )
            new_players += 1
    
    if new_players > 0:
        messages.success(request, f'Added {new_players} new player{"s" if new_players != 1 else ""} to the payment.')
    else:
        messages.info(request, 'No new players to add.')
    
    return redirect('teams:payment_edit', team_id=team.id, season_id=season.id, payment_id=payment.id)

@login_required
def update_condition(request):
    if request.method == 'POST':
        log_error(
            request=request,
            error_message="Condition update initiated",
            error_type="UserActivity",
            extra_context={
                "user_email": request.user.email,
                "user_id": request.user.id,
                "path": request.path,
                "method": request.method,
                "condition": request.POST.get('condition')
            }
        )
        
        try:
            condition = request.POST.get('condition')
            if condition and hasattr(request.user, 'profile'):
                profile = request.user.profile
                if condition in dict(Profile.CONDITION_CHOICES):
                    old_condition = profile.condition
                    profile.condition = condition
                    profile.save()
                    
                    log_error(
                        request=request,
                        error_message="Condition updated successfully",
                        error_type="UserActivity",
                        extra_context={
                            "user_email": request.user.email,
                            "user_id": request.user.id,
                            "old_condition": old_condition,
                            "new_condition": condition,
                            "profile_id": profile.id
                        }
                    )
                else:
                    log_error(
                        request=request,
                        error_message="Invalid condition value",
                        error_type="ValidationError",
                        extra_context={
                            "user_email": request.user.email,
                            "user_id": request.user.id,
                            "invalid_condition": condition,
                            "allowed_conditions": dict(Profile.CONDITION_CHOICES)
                        }
                    )
            else:
                log_error(
                    request=request,
                    error_message="Missing condition or profile",
                    error_type="ValidationError",
                    extra_context={
                        "user_email": request.user.email,
                        "user_id": request.user.id,
                        "has_profile": hasattr(request.user, 'profile'),
                        "condition_provided": bool(condition)
                    }
                )
        except Exception as e:
            log_error(
                request=request,
                error_message=f"Failed to update condition: {str(e)}",
                error_type="SystemError",
                extra_context={
                    "user_email": request.user.email,
                    "user_id": request.user.id,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "traceback": traceback.format_exc()
                }
            )
    
    # Redirect back to the dashboard
    return redirect('teams:dashboard')

def send_invitation_email(email, team, invitation_url, role='Player', is_team_admin=False, is_official=False):
    """Send an invitation email to a prospective team member."""
    subject = f'Invitation to join {team.name}'
    context = {
        'team': team,
        'invite_url': invitation_url,
        'role': role,
        'is_team_admin': is_team_admin,
        'is_official': is_official
    }
    html_message = render_to_string('teams/email/team_invitation.html', context)
    plain_message = f'You have been invited to join {team.name}. Click here to accept: {invitation_url}'
    
    try:
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            html_message=html_message,
            fail_silently=False,
        )
    except Exception as e:
        log_error(
            None,
            error_message=f"Failed to send invitation email: {str(e)}",
            error_type="EmailError",
            extra_context={
                "email": email,
                "team": team.name,
                "error": str(e)
            }
        )
        raise

