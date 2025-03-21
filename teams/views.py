from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import login as auth_login
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.core.mail import send_mail
from django.urls import reverse, reverse_lazy
from django.utils.crypto import get_random_string
from django.http import HttpResponseForbidden, JsonResponse, HttpResponse
from django.db import transaction
from .models import Team, TeamMember, Season, Match, Profile, Payment, PlayerPayment, PlayerMatchStats, TeamMemberProfile
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
from django.db.models.functions import Coalesce
from .utils.logging_utils import log_error, log_upload_error, logger
import os
import traceback
import secrets
import json
from django.core.exceptions import PermissionDenied
from django.utils.html import strip_tags
from django.contrib.sites.shortcuts import get_current_site
from django.contrib.auth import views as auth_views
from .utils.team_utils import get_current_team
import logging

User = get_user_model()
logger = logging.getLogger(__name__)

def get_current_team(user):
    """Get the current team for a user from their session or active memberships."""
    # Get all active team memberships for the user
    team_memberships = TeamMember.objects.filter(
        user=user,
        is_active=True
    ).select_related('team')
    
    if not team_memberships.exists():
        return None

    # Try to get team from session
    current_team_id = user.request.session.get('current_team') if hasattr(user, 'request') else None
    
    if current_team_id:
        # Verify the team from session is in user's active teams
        team_from_session = team_memberships.filter(team_id=current_team_id).first()
        if team_from_session:
            return team_from_session.team
    
    # If no valid team in session, return first active team and update session
    first_team = team_memberships.first()
    if not first_team:
        return None
        
    if hasattr(user, 'request'):
        user.request.session['current_team'] = first_team.team.id
    return first_team.team

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
    logger.info(f"Dashboard access for user {request.user.email}")
    try:
        current_team_id = request.session.get('current_team')
        logger.info(f"Current team ID from session: {current_team_id}")
        
        if not current_team_id:
            logger.error("No current team ID in session")
            messages.error(request, "Please select a team first.")
            return redirect('teams:team_list')
            
        team = Team.objects.get(id=current_team_id)
        logger.info(f"Found team: {team.name}")
        
        membership = TeamMember.objects.filter(team=team, user=request.user).first()
        logger.info(f"Found membership: {membership}")
        
        if not membership:
            logger.error(f"No membership found for user {request.user.email} in team {team.name}")
            messages.error(request, "You are not a member of this team.")
            return redirect('teams:team_list')
            
        profile = TeamMemberProfile.objects.filter(team_member=membership).first()
        logger.info(f"Found profile: {profile}")
        
        # Get current season
        current_season = Season.objects.filter(team=team, is_active=True).first()
        logger.info(f"Current season: {current_season}")
        
        # Get upcoming matches if there's a current season
        upcoming_matches = None
        if current_season:
            upcoming_matches = Match.objects.filter(
                season=current_season,
                match_date__gte=timezone.now().date()
            ).order_by('match_date', 'match_time')
        
        # Get upcoming birthdays
        upcoming_birthdays = team.get_upcoming_birthdays()
        
        # Get team members for the team roster section - modified to handle missing profiles
        team_members = TeamMember.objects.filter(
            team=team,
            is_active=True
        ).select_related(
            'user',
            'teammemberprofile',
            'teammemberprofile__position'
        ).annotate(
            sort_number=Coalesce('teammemberprofile__player_number', Value(999))
        ).order_by('sort_number')
        
        # Get all team memberships for the user
        team_memberships = TeamMember.objects.filter(
            user=request.user,
            is_active=True
        ).select_related('team').order_by('team__name')
        
        # Get pending payments with amount > 0 and calculate verification percentage
        pending_payments = None
        if current_season:
            pending_payments = PlayerPayment.objects.filter(
                payment__season=current_season,
                player=membership,
                amount__gt=0
            ).select_related('payment').annotate(
                total_players=models.Count(
                    'payment__player_payments',
                    filter=models.Q(payment__player_payments__amount__gt=0)
                ),
                verified_players=models.Count(
                    'payment__player_payments',
                    filter=models.Q(payment__player_payments__amount__gt=0, payment__player_payments__admin_verified=True)
                ),
                verification_percentage=models.Case(
                    When(total_players__gt=0,
                         then=models.ExpressionWrapper(
                             100.0 * models.F('verified_players') / models.F('total_players'),
                             output_field=models.FloatField()
                         )),
                    default=Value(0.0),
                    output_field=models.FloatField(),
                )
            ).order_by('payment__due_date')
        
        context = {
            'team': team,
            'membership': membership,
            'profile': profile,
            'current_team': team,
            'current_season': current_season,
            'is_team_admin': membership.is_team_admin or membership.role == TeamMember.Role.MANAGER,
            'upcoming_birthdays': upcoming_birthdays if upcoming_birthdays else None,
            'team_members': team_members,
            'current_team_member': membership,
            'pending_payments': pending_payments,
            'today': timezone.now().date(),
            'team_memberships': team_memberships,  # Add team memberships to context
            'upcoming_matches': upcoming_matches  # Add upcoming matches to context
        }
        
        # Debug logging
        log_error(
            request=request,
            error_message="Dashboard context debug",
            error_type="ViewDebug",
            extra_context={
                "context_keys": list(context.keys()),
                "has_team": bool(team),
                "has_membership": bool(membership),
                "has_profile": bool(profile),
                "has_current_season": bool(current_season),
                "has_upcoming_birthdays": bool(upcoming_birthdays),
                "team_members_count": team_members.count() if team_members else 0,
                "has_pending_payments": bool(pending_payments),
                "has_upcoming_matches": bool(upcoming_matches),
                "is_team_admin": context['is_team_admin']
            }
        )
        
        return render(request, 'teams/dashboard.html', context)
    except Exception as e:
        logger.error(f"Error in dashboard: {str(e)}", exc_info=True)
        messages.error(request, "An error occurred while loading the dashboard.")
        return redirect('teams:team_list')

@login_required
def switch_team(request, team_id):
    logger.info(f"Attempting to switch to team {team_id} for user {request.user.email}")
    try:
        team = Team.objects.get(id=team_id)
        logger.info(f"Found team: {team.name}")
        
        membership = TeamMember.objects.filter(team=team, user=request.user).first()
        logger.info(f"Found membership: {membership}")
        
        if not membership:
            logger.error(f"No membership found for user {request.user.email} in team {team.name}")
            messages.error(request, "You are not a member of this team.")
            return redirect('teams:team_list')
            
        request.session['current_team'] = team.id  # Changed from current_team_id to current_team
        logger.info(f"Set session team_id to {team.id}")
        
        return redirect('teams:dashboard')
    except Exception as e:
        logger.error(f"Error switching teams: {str(e)}", exc_info=True)
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
        error_message="Team members page access - ENTRY POINT",
        error_type="ViewDebug",
        extra_context={
            "user_email": request.user.email,
            "user_id": request.user.id,
            "team_id": team_id,
            "path": request.path,
            "method": request.method,
            "session_id": request.session.session_key,
            "current_team_in_session": request.session.get('current_team'),
            "all_session_data": dict(request.session)
        }
    )
    
    try:
        team = get_object_or_404(Team, id=team_id)
        team_member = get_object_or_404(TeamMember, team=team, user=request.user, is_active=True)
        
        # Get the filter parameter
        show_active_only = request.GET.get('active_only', 'false').lower() == 'true'
        
        # Get active members with fresh data
        active_members_query = TeamMember.objects.select_related(
            'user',
            'teammemberprofile',
            'teammemberprofile__position'
        ).filter(
            team=team,
            is_active=True
        ).order_by(
            'teammemberprofile__player_number'
        ).distinct()
        
        # Apply active filter if requested
        if show_active_only:
            active_members_query = active_members_query.filter(teammemberprofile__active_player=True)
        
        # Force a fresh query by adding a timestamp
        active_members = active_members_query.extra(
            select={'_timestamp': "'%s'" % timezone.now().isoformat()}
        ).annotate(
            position_order=Case(
                When(teammemberprofile__position__type='GK', then=Value(1)),
                When(teammemberprofile__position__type='DEF', then=Value(2)),
                When(teammemberprofile__position__type='MID', then=Value(3)),
                When(teammemberprofile__position__type='ATT', then=Value(4)),
                default=Value(5),
                output_field=IntegerField(),
            )
        ).order_by('position_order', 'teammemberprofile__player_number')
        
        # Get pending invitations
        pending_invitations = TeamMember.objects.filter(
            team=team,
            is_active=False,
            invitation_token__isnull=False,
            invitation_accepted=False
        )
        
        log_error(
            request=request,
            error_message="Team members loaded successfully",
            error_type="ViewDebug",
            extra_context={
                "active_members_count": active_members.count(),
                "pending_invitations_count": pending_invitations.count(),
                "show_active_only": show_active_only
            }
        )
        
        # Get current season for the team
        current_season = Season.objects.filter(team=team, is_active=True).first()
        
        context = {
            'team': team,
            'active_members': active_members,
            'pending_invitations': pending_invitations,
            'user': request.user,
            'user_is_admin': team_member.is_team_admin or team_member.role == TeamMember.Role.MANAGER,
            'show_active_only': show_active_only,
            'current_team': team,  # Add this for navbar
            'current_season': current_season,  # Add this for navbar
            'is_team_admin': team_member.is_team_admin or team_member.role == TeamMember.Role.MANAGER  # Add this for navbar
        }
        
        log_error(
            request=request,
            error_message="About to render template",
            error_type="ViewDebug",
            extra_context={
                "template": "teams/team_members.html",
                "context_keys": list(context.keys()),
                "is_team_admin": context['is_team_admin'],
                "current_team_id": context['current_team'].id,
                "has_current_season": current_season is not None
            }
        )
        
        return render(request, 'teams/team_members.html', context)
        
    except (Team.DoesNotExist, TeamMember.DoesNotExist) as e:
        log_error(
            request=request,
            error_message="Team members access denied - Object not found",
            error_type="AuthorizationError",
            extra_context={
                "user_email": request.user.email,
                "user_id": request.user.id,
                "team_id": team_id,
                "error": str(e),
                "error_type": type(e).__name__,
                "exception_class": e.__class__.__name__
            }
        )
        messages.error(request, "You don't have access to this team.")
        return redirect('teams:team_list')
    except Exception as e:
        log_error(
            request=request,
            error_message="Unexpected error in team members view",
            error_type="SystemError",
            extra_context={
                "user_email": request.user.email,
                "user_id": request.user.id,
                "team_id": team_id,
                "error": str(e),
                "error_type": type(e).__name__,
                "traceback": traceback.format_exc(),
                "exception_class": e.__class__.__name__
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
            
            # Log the invitation data
            log_error(
                request=request,
                error_message="Creating new invitation",
                error_type="InvitationDebug",
                extra_context={
                    "email": email,
                    "team_id": team.id,
                    "is_official": is_official,
                    "active_player": active_player,
                    "current_session_id": request.session.session_key,
                    "session_data": dict(request.session)
                }
            )
            
            # Check if user already exists
            existing_user = User.objects.filter(email=email).first()
            
            try:
                with transaction.atomic():
                    token = secrets.token_urlsafe(32)
                    
                    # Log token generation
                    log_error(
                        request=request,
                        error_message="Generated invitation token",
                        error_type="InvitationDebug",
                        extra_context={
                            "token": token,
                            "email": email
                        }
                    )
                    
                    # Check if there's an existing inactive membership
                    existing_member = TeamMember.objects.filter(
                        team=team,
                        email=email
                    ).first()
                    
                    if existing_member:
                        if existing_member.is_active:
                            messages.error(request, f'{email} is already a member of this team.')
                            return redirect('teams:team_members', team_id=team.id)
                        else:
                            # Update existing inactive membership
                            existing_member.role = role
                            existing_member.is_team_admin = is_team_admin
                            existing_member.invitation_token = token
                            existing_member.user = existing_user  # Link to existing user if any
                            existing_member.is_official = is_official
                            existing_member.active_player = active_player
                            existing_member.save()
                            team_member = existing_member
                    else:
                        # Create new inactive team member
                        team_member = TeamMember.objects.create(
                            team=team,
                            email=email,
                            role=role,
                            is_team_admin=is_team_admin,
                            is_active=False,
                            invitation_token=token,
                            user=existing_user,  # Link to existing user if any
                            is_official=is_official,
                            active_player=active_player
                        )
                    
                    # Log member creation
                    log_error(
                        request=request,
                        error_message="Created team member",
                        error_type="InvitationDebug",
                        extra_context={
                            "token": token,
                            "email": email,
                            "member_data": {
                                "id": team_member.id,
                                "is_official": team_member.is_official,
                                "active_player": team_member.active_player
                            }
                        }
                    )
                    
                    # Send invitation email
                    current_site = get_current_site(request)
                    if existing_user:
                        # Send invitation for existing user
                        invitation_url = request.build_absolute_uri(
                            reverse('teams:accept_invitation') + f'?token={token}'
                        )
                        send_invitation_email(email, team, invitation_url, role, is_team_admin, is_official)
                        messages.success(request, f'Invitation sent to existing user {email}')
                    else:
                        # Send registration invitation for new user
                        invitation_url = request.build_absolute_uri(
                            reverse('teams:register') + f'?token={token}'
                        )
                        send_invitation_email(email, team, invitation_url, role, is_team_admin, is_official)
                        messages.success(request, f'Registration invitation sent to {email}')
                    
                    return redirect('teams:team_members', team_id=team.id)
                    
            except Exception as e:
                log_error(
                    request=request,
                    error_message=f"Failed to create invitation: {str(e)}",
                    error_type="InvitationError",
                    extra_context={
                        "email": email,
                        "team_id": team.id,
                        "error": str(e)
                    }
                )
                messages.error(request, f'Error creating invitation: {str(e)}')
    else:
        form = TeamMemberInviteForm(team)
    
    return render(request, 'teams/invite_member.html', {
        'form': form,
        'team': team
    })

def send_existing_user_notification(email, team, dashboard_url, role='Player', is_team_admin=False, is_official=False):
    """Send a notification email to an existing user when added to a new team."""
    subject = f'You have been added to {team.name}'
    context = {
        'team': team,
        'dashboard_url': dashboard_url,
        'role': role,
        'is_team_admin': is_team_admin,
        'is_official': is_official
    }
    html_message = render_to_string('teams/email/team_addition.html', context)
    plain_message = f'You have been added to {team.name}. Visit your dashboard to complete your team profile: {dashboard_url}'
    
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
            error_message=f"Failed to send team addition email: {str(e)}",
            error_type="EmailError",
            extra_context={
                "email": email,
                "team": team.name,
                "error": str(e)
            }
        )
        raise

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
    
    # Log initial state
    log_error(
        request=request,
        error_message="Registration process started",
        error_type="RegistrationDebug",
        extra_context={
            "token": token,
            "session_id": request.session.session_key,
            "all_session_keys": list(request.session.keys())
        }
    )
    
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
            error_message="Processing registration POST request",
            error_type="RegistrationDebug",
            extra_context={
                "token": token,
                "team_member_data": {
                    "email": team_member.email,
                    "team": team_member.team.name,
                    "role": team_member.role,
                    "is_official": team_member.is_official,
                    "active_player": team_member.active_player
                }
            }
        )
        
        form = UserRegistrationForm(request.POST, request.FILES, email=team_member.email)
        if form.is_valid():
            try:
                with transaction.atomic():
                    # Create the user first
                    user = form.save()
                    
                    # Update the team member with the new user
                    team_member.user = user
                    team_member.is_active = True
                    team_member.invitation_accepted = True
                    team_member.invitation_token = None
                    team_member.save()
                    
                    # Log profile creation attempt
                    log_error(
                        request=request,
                        error_message="About to create/update profile",
                        error_type="RegistrationDebug",
                        extra_context={
                            "token": token,
                            "is_official": team_member.is_official,
                            "active_player": team_member.active_player,
                            "existing_profile": hasattr(team_member, 'teammemberprofile')
                        }
                    )
                    
                    # Create or update the profile
                    profile_data = {
                        'team_member': team_member,
                        'is_official': team_member.is_official,
                        'active_player': team_member.active_player,
                        'level': form.cleaned_data['level'],
                        'condition': 'NORMAL',
                        'player_number': form.cleaned_data['player_number'],
                        'position': form.cleaned_data['position']
                    }
                    
                    # Get or create the profile
                    profile, created = TeamMemberProfile.objects.get_or_create(
                        team_member=team_member,
                        defaults=profile_data
                    )
                    
                    # If profile already existed, update it
                    if not created:
                        for key, value in profile_data.items():
                            setattr(profile, key, value)
                        profile.save()
                    
                    # Create or update the user profile
                    user_profile, _ = Profile.objects.get_or_create(user=user)
                    user_profile.rut = form.cleaned_data['rut']
                    user_profile.country = form.cleaned_data['country']
                    user_profile.date_of_birth = form.cleaned_data['date_of_birth']
                    user_profile.save()
                    
                    # Log profile creation/update result
                    log_error(
                        request=request,
                        error_message="Profile creation/update result",
                        error_type="RegistrationDebug",
                        extra_context={
                            "token": token,
                            "profile_id": profile.id,
                            "was_created": created,
                            "final_is_official": profile.is_official,
                            "final_active_player": profile.active_player,
                            "user_profile_id": user_profile.id
                        }
                    )
                    
                    # Log in the user
                    auth_login(request, user)
                    
                    messages.success(request, f'Registration successful! You are now a member of {team_member.team.name}.')
                    return redirect('teams:dashboard')
                    
            except Exception as e:
                log_error(
                    request=request,
                    error_message=f"Registration failed: {str(e)}",
                    error_type="RegistrationError",
                    extra_context={
                        "token": token,
                        "error": str(e),
                        "traceback": traceback.format_exc()
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
        form = UserRegistrationForm(initial={'email': team_member.email}, email=team_member.email)
    
    return render(request, 'teams/register.html', {
        'form': form,
        'is_official': team_member.is_official,
        'team': team_member.team,
        'role': team_member.get_role_display(),
        'email': team_member.email
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
                    team_member = TeamMember.objects.create(
                        user=user,
                        team=team,
                        role=form.cleaned_data['role'],
                        is_team_admin=form.cleaned_data['is_team_admin'],
                        is_active=True,
                        invitation_accepted=True
                    )

                    # Create the team member profile
                    TeamMemberProfile.objects.create(
                        team_member=team_member,
                        level=1,
                        condition='NORMAL',
                        active_player=True
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
def edit_profile(request, team_id):
    team = get_object_or_404(Team, id=team_id)
    team_member = get_object_or_404(TeamMember, team=team, user=request.user, is_active=True)
    
    if request.method == 'POST':
        form = UserProfileForm(request.POST, request.FILES, instance=request.user, team=team)
        if form.is_valid():
            try:
                user = form.save(commit=False)
                profile = Profile.objects.get_or_create(user=user)[0]
                
                # Handle profile picture upload
                if form.cleaned_data.get('profile_picture'):
                    # Validate file size
                    file = form.cleaned_data['profile_picture']
                    if file.size > 2 * 1024 * 1024:  # 2MB limit
                        messages.error(request, 'Profile picture must be less than 2MB')
                        return render(request, 'teams/edit_profile.html', {
                            'form': form, 
                            'team': team,
                            'is_team_admin': team_member.is_team_admin or team_member.role == TeamMember.Role.MANAGER,
                            'current_team': team,
                            'current_season': Season.objects.filter(team=team, is_active=True).first()
                        })
                    
                    # Validate file type using file extension
                    allowed_extensions = ['.jpg', '.jpeg', '.png']
                    file_extension = os.path.splitext(file.name)[1].lower()
                    if file_extension not in allowed_extensions:
                        messages.error(request, 'Profile picture must be JPEG or PNG')
                        return render(request, 'teams/edit_profile.html', {
                            'form': form, 
                            'team': team,
                            'is_team_admin': team_member.is_team_admin or team_member.role == TeamMember.Role.MANAGER,
                            'current_team': team,
                            'current_season': Season.objects.filter(team=team, is_active=True).first()
                        })
                
                # Save user and shared profile data
                user.save()
                profile.rut = form.cleaned_data['rut']
                profile.country = form.cleaned_data['country']
                profile.date_of_birth = form.cleaned_data['date_of_birth']
                profile.save()
                
                # Save team-specific profile data
                team_profile = TeamMemberProfile.objects.get_or_create(team_member=team_member)[0]
                team_profile.player_number = form.cleaned_data['player_number']
                team_profile.position = form.cleaned_data['position']
                team_profile.level = form.cleaned_data['level']
                team_profile.description = form.cleaned_data['description']
                if form.cleaned_data.get('profile_picture'):
                    team_profile.profile_picture = form.cleaned_data['profile_picture']
                team_profile.save()
                
                messages.success(request, 'Profile updated successfully')
                return redirect('teams:dashboard')
            except Exception as e:
                messages.error(request, 'An error occurred while updating your profile')
                return render(request, 'teams/edit_profile.html', {
                    'form': form, 
                    'team': team,
                    'is_team_admin': team_member.is_team_admin or team_member.role == TeamMember.Role.MANAGER,
                    'current_team': team,
                    'current_season': Season.objects.filter(team=team, is_active=True).first()
                })
    else:
        form = UserProfileForm(instance=request.user, team=team)
    
    return render(request, 'teams/edit_profile.html', {
        'form': form, 
        'team': team,
        'is_team_admin': team_member.is_team_admin or team_member.role == TeamMember.Role.MANAGER,
        'current_team': team,
        'current_season': Season.objects.filter(team=team, is_active=True).first()
    })

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
    
    # Get upcoming birthdays
    upcoming_birthdays = team.get_upcoming_birthdays()
    
    context = {
        'team': team,
        'season': season,
        'upcoming_matches': upcoming_matches,
        'past_matches': past_matches,
        'is_admin': team_member.is_team_admin or team_member.role == TeamMember.Role.MANAGER,
        'upcoming_birthdays': upcoming_birthdays if upcoming_birthdays else None
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
            try:
                match = form.save(commit=False)
                match.season = season
                match.save()
                messages.success(request, f'Match against {match.opponent} has been updated.')
                return redirect('teams:season_detail', team_id=team.id, season_id=season.id)
            except Exception as e:
                log_error(
                    request=request,
                    error_message=f"Failed to update match: {str(e)}",
                    error_type="MatchUpdateError",
                    extra_context={
                        "team_id": team_id,
                        "season_id": season_id,
                        "match_id": match_id,
                        "error": str(e),
                        "error_type": type(e).__name__,
                        "traceback": traceback.format_exc()
                    }
                )
                messages.error(request, 'An error occurred while updating the match.')
                return render(request, 'teams/match_form.html', {
                    'form': form,
                    'team': team,
                    'season': season,
                    'match': match,
                    'is_admin': True,
                    'title': 'Edit Match'
                })
    else:
        form = MatchForm(instance=match, season=season)
    
    return render(request, 'teams/match_form.html', {
        'form': form,
        'team': team,
        'season': season,
        'match': match,
        'is_admin': True,
        'title': 'Edit Match'
    })

@login_required
def edit_member(request, team_id, user_id):
    team = get_object_or_404(Team, id=team_id)
    member_to_edit = get_object_or_404(User, id=user_id)
    team_member = get_object_or_404(TeamMember, team=team, user=member_to_edit, is_active=True)
    
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
    requester_member = get_object_or_404(TeamMember, team=team, user=request.user, is_active=True)
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
        form = AdminMemberProfileForm(request.POST, request.FILES, instance=member_to_edit, team=team)
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
                    
                    # Handle file validation before saving
                    if form.cleaned_data.get('profile_picture'):
                        file = form.cleaned_data['profile_picture']
                        # Validate file size
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
                            return render(request, 'teams/edit_member.html', {
                                'form': form,
                                'team': team,
                                'member': member_to_edit,
                                'team_member': team_member
                            })
                        
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
                            return render(request, 'teams/edit_member.html', {
                                'form': form,
                                'team': team,
                                'member': member_to_edit,
                                'team_member': team_member
                            })
                    
                    # Save the form
                    form.save()
                    
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
                                "player_number": form.cleaned_data['player_number'],
                                "position": str(form.cleaned_data['position']),
                                "level": form.cleaned_data['level'],
                                "is_official": form.cleaned_data['is_official'],
                                "active_player": form.cleaned_data['active_player'],
                                "country": form.cleaned_data['country'],
                                "has_profile_picture": bool(form.cleaned_data.get('profile_picture'))
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
                return render(request, 'teams/edit_member.html', {
                    'form': form,
                    'team': team,
                    'member': member_to_edit,
                    'team_member': team_member
                })
    else:
        form = AdminMemberProfileForm(instance=member_to_edit, team=team)
    
    return render(request, 'teams/edit_member.html', {
        'form': form,
        'team': team,
        'member': member_to_edit,
        'team_member': team_member
    })

@login_required
def payment_list(request, team_id, season_id):
    team = get_object_or_404(Team, id=team_id)
    season = get_object_or_404(Season, id=season_id)
    if not request.user.is_superuser and not TeamMember.objects.filter(team=team, user=request.user, is_team_admin=True).exists():
        return HttpResponseForbidden("You don't have permission to manage payments.")
    
    # Get payments with annotated sum and count of players with payments
    payments = Payment.objects.filter(season=season).annotate(
        sum_of_payments=models.Sum('player_payments__amount'),
        players_with_payments=models.Count('player_payments', filter=models.Q(player_payments__amount__gt=0))
    )
    
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
                    
                    # Create player payments for official players
                    official_players = TeamMember.objects.filter(
                        team=team,
                        role=TeamMember.Role.PLAYER,
                        teammemberprofile__is_official=True,
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
        
        # Parse JSON data from request body
        try:
            data = json.loads(request.body)
            is_paid = data.get('is_paid', False)
            send_email = data.get('send_email', False)
        except json.JSONDecodeError:
            return JsonResponse({'status': 'error', 'message': 'Invalid JSON data'}, status=400)
        
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
            if not is_paid:
                # Admin unmarking a payment (from paid to unpaid)
                player_payment.mark_as_unpaid(is_admin=True)
            else:
                # Admin marking as paid (without automatic verification)
                player_payment.mark_as_paid(is_admin=False)  # Changed from True to False
        # Handle player actions
        else:
            if player_payment.admin_verified:
                return HttpResponseForbidden("This payment has been verified by an admin and cannot be modified.")
            
            if not is_paid:
                # Player canceling their payment notification
                player_payment.mark_as_unpaid()
            else:
                # Player marking as paid (pending approval)
                player_payment.mark_as_paid()
                
                # Send email notification to team admins only if send_email is True
                if send_email:
                    admin_emails = [
                        member.user.email 
                        for member in TeamMember.objects.filter(
                            team=team, 
                            is_team_admin=True, 
                            is_active=True
                        ).select_related('user')
                    ]
                    
                    if admin_emails:
                        subject = f'Payment Marked as Paid - {team.name}'
                        context = {
                            'team': team,
                            'player': request.user,
                            'payment': player_payment.payment,
                            'amount': player_payment.amount,
                            'protocol': request.scheme,
                            'domain': request.get_host(),
                        }
                        html_message = render_to_string('teams/email/payment_notification.html', context)
                        plain_message = f'{request.user.get_full_name()} marked payment "{player_payment.payment.name}" as paid. Please verify.'
                        
                        try:
                            send_mail(
                                subject=subject,
                                message=plain_message,
                                from_email=settings.DEFAULT_FROM_EMAIL,
                                recipient_list=admin_emails,
                                html_message=html_message,
                                fail_silently=False,
                            )
                        except Exception as e:
                            log_error(
                                request=request,
                                error_message=f"Failed to send payment notification email: {str(e)}",
                                error_type="EmailError",
                                extra_context={
                                    "team_id": team.id,
                                    "payment_id": payment_id,
                                    "player_payment_id": player_payment_id,
                                    "error": str(e)
                                }
                            )
        
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
        
        # Check if user has no teams
        if not team_memberships.exists():
            messages.info(request, "You are not a member of any team. Please contact an administrator to join a team.")
        
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
        # Return to team list instead of dashboard to avoid redirect loop
        return render(request, 'teams/team_list.html', {'team_memberships': []})

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
        teammemberprofile__is_official=True,
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
def update_condition(request, team_id):
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
                "condition": request.POST.get('condition'),
                "team_id": team_id
            }
        )
        
        try:
            condition = request.POST.get('condition')
            team = get_object_or_404(Team, id=team_id)
            if condition:
                team_member = TeamMember.objects.get(user=request.user, team=team, is_active=True)
                if condition in dict(TeamMemberProfile.CONDITION_CHOICES):
                    old_condition = team_member.teammemberprofile.condition
                    team_member.teammemberprofile.condition = condition
                    team_member.teammemberprofile.save()
                    
                    log_error(
                        request=request,
                        error_message="Condition updated successfully",
                        error_type="UserActivity",
                        extra_context={
                            "user_email": request.user.email,
                            "user_id": request.user.id,
                            "old_condition": old_condition,
                            "new_condition": condition,
                            "team_member_id": team_member.id,
                            "team_id": team_id
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
                            "allowed_conditions": dict(TeamMemberProfile.CONDITION_CHOICES),
                            "team_id": team_id
                        }
                    )
            else:
                log_error(
                    request=request,
                    error_message="Missing condition",
                    error_type="ValidationError",
                    extra_context={
                        "user_email": request.user.email,
                        "user_id": request.user.id,
                        "condition_provided": bool(condition),
                        "team_id": team_id
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
                    "traceback": traceback.format_exc(),
                    "team_id": team_id
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

@login_required
def player_card(request, team_id, user_id):
    log_error(
        request=request,
        error_message="Player card view accessed",
        error_type="ViewAccess",
        extra_context={
            "user_email": request.user.email,
            "user_id": request.user.id,
            "requested_team_id": team_id,
            "requested_user_id": user_id,
            "path": request.path,
            "method": request.method
        }
    )
    
    try:
        team = get_object_or_404(Team, id=team_id)
        log_error(
            request=request,
            error_message="Team found",
            error_type="ViewDebug",
            extra_context={
                "team_id": team.id,
                "team_name": team.name
            }
        )
        
        user = get_object_or_404(User, id=user_id)
        log_error(
            request=request,
            error_message="User found",
            error_type="ViewDebug",
            extra_context={
                "target_user_id": user.id,
                "target_user_email": user.email,
                "target_user_name": user.get_full_name()
            }
        )
        
        # Check if the requesting user is a member of the team
        requesting_user_membership = get_object_or_404(TeamMember, team=team, user=request.user, is_active=True)
        
        # Get the player's team membership
        team_member = get_object_or_404(TeamMember, team=team, user=user, is_active=True)
        log_error(
            request=request,
            error_message="Team membership found",
            error_type="ViewDebug",
            extra_context={
                "team_member_id": team_member.id,
                "role": team_member.role,
                "is_active": team_member.is_active,
                "is_team_admin": team_member.is_team_admin
            }
        )
        
        # Get current season
        current_season = get_current_season(team)
        
        # Get player stats
        season_stats = PlayerMatchStats.get_player_totals(team_member, current_season) if current_season else None
        all_time_stats = PlayerMatchStats.get_player_totals(team_member)
        
        context = {
            'member': team_member,
            'team': team,
            'is_team_admin': requesting_user_membership.is_team_admin or requesting_user_membership.role == TeamMember.Role.MANAGER,
            'current_season': current_season,
            'season_stats': season_stats,
            'all_time_stats': all_time_stats,
        }
        
        log_error(
            request=request,
            error_message="Rendering player card template",
            error_type="ViewDebug",
            extra_context={
                "template": "teams/player_card.html",
                "context_keys": list(context.keys())
            }
        )
        
        return render(request, 'teams/player_card.html', context)
        
    except Team.DoesNotExist:
        log_error(
            request=request,
            error_message="Team not found",
            error_type="NotFoundError",
            extra_context={
                "requested_team_id": team_id
            }
        )
        raise
    except User.DoesNotExist:
        log_error(
            request=request,
            error_message="User not found",
            error_type="NotFoundError",
            extra_context={
                "requested_user_id": user_id
            }
        )
        raise
    except TeamMember.DoesNotExist:
        log_error(
            request=request,
            error_message="Team membership not found",
            error_type="NotFoundError",
            extra_context={
                "team_id": team_id,
                "user_id": user_id
            }
        )
        raise
    except Exception as e:
        log_error(
            request=request,
            error_message=f"Unexpected error in player card view: {str(e)}",
            error_type="SystemError",
            extra_context={
                "error": str(e),
                "error_type": type(e).__name__,
                "traceback": traceback.format_exc()
            }
        )
        raise

@login_required
def match_stats_edit(request, team_id, season_id, match_id):
    log_error(
        request=request,
        error_message="Match stats edit page accessed",
        error_type="ViewAccess",
        extra_context={
            "user_email": request.user.email,
            "user_id": request.user.id,
            "team_id": team_id,
            "season_id": season_id,
            "match_id": match_id,
            "path": request.path,
            "method": request.method
        }
    )
    
    try:
        team = get_object_or_404(Team, id=team_id)
        season = get_object_or_404(Season, id=season_id, team=team)
        match = get_object_or_404(Match, id=match_id, season=season)
        
        # Check if user is team admin
        if not is_user_team_admin(request.user, team):
            log_error(
                request=request,
                error_message="Unauthorized access attempt to match stats edit",
                error_type="PermissionError",
                extra_context={
                    "user_email": request.user.email,
                    "user_id": request.user.id,
                    "team_id": team_id,
                    "match_id": match_id
                }
            )
            raise PermissionDenied("You must be a team admin to edit match stats.")
        
        # Get all active players in the team
        players = TeamMember.objects.filter(
            team=team,
            is_active=True,
            teammemberprofile__active_player=True,
            role=TeamMember.Role.PLAYER
        ).select_related('user', 'teammemberprofile')
        
        log_error(
            request=request,
            error_message="Retrieved active players for match stats",
            error_type="ViewDebug",
            extra_context={
                "team_id": team_id,
                "match_id": match_id,
                "active_players_count": players.count(),
                "player_ids": list(players.values_list('id', flat=True))
            }
        )
        
        # Get or create stats for each player
        stats_dict = {}
        for player in players:
            stat, created = PlayerMatchStats.objects.get_or_create(
                match=match,
                player=player,
                defaults={'played': False}
            )
            stats_dict[player.id] = {
                'played': stat.played,
                'goals': stat.goals,
                'assists': stat.assists,
                'yellow_cards': stat.yellow_cards,
                'red_cards': stat.red_cards
            }
        
        if request.method == 'POST':
            try:
                with transaction.atomic():
                    for player in players:
                        player_stats = PlayerMatchStats.objects.get(match=match, player=player)
                        player_stats.played = request.POST.get(f'played_{player.id}') == 'on'
                        player_stats.goals = int(request.POST.get(f'goals_{player.id}', 0))
                        player_stats.assists = int(request.POST.get(f'assists_{player.id}', 0))
                        player_stats.yellow_cards = int(request.POST.get(f'yellow_cards_{player.id}', 0))
                        player_stats.red_cards = int(request.POST.get(f'red_cards_{player.id}', 0))
                        player_stats.save()
                        
                        log_error(
                            request=request,
                            error_message="Updated player match stats",
                            error_type="StatsUpdate",
                            extra_context={
                                "player_id": player.id,
                                "player_email": player.user.email,
                                "match_id": match_id,
                                "stats": {
                                    "played": player_stats.played,
                                    "goals": player_stats.goals,
                                    "assists": player_stats.assists,
                                    "yellow_cards": player_stats.yellow_cards,
                                    "red_cards": player_stats.red_cards
                                }
                            }
                        )
                
                messages.success(request, 'Match statistics updated successfully.')
                return redirect('teams:season_detail', team_id=team_id, season_id=season_id)
            except Exception as e:
                log_error(
                    request=request,
                    error_message=f"Error updating match statistics: {str(e)}",
                    error_type="StatsUpdateError",
                    extra_context={
                        "error": str(e),
                        "traceback": traceback.format_exc(),
                        "team_id": team_id,
                        "match_id": match_id,
                        "post_data": dict(request.POST)
                    }
                )
                messages.error(request, f'Error updating match statistics: {str(e)}')
        
        context = {
            'team': team,
            'season': season,
            'match': match,
            'players': players,
            'stats': stats_dict
        }
        
        log_error(
            request=request,
            error_message="Rendering match stats edit template",
            error_type="ViewDebug",
            extra_context={
                "context_keys": list(context.keys()),
                "stats_count": len(stats_dict)
            }
        )
        
        return render(request, 'teams/match_stats_edit.html', context)
        
    except Exception as e:
        log_error(
            request=request,
            error_message=f"Unexpected error in match stats edit view: {str(e)}",
            error_type="SystemError",
            extra_context={
                "error": str(e),
                "traceback": traceback.format_exc(),
                "team_id": team_id,
                "season_id": season_id,
                "match_id": match_id
            }
        )
        raise

@login_required
def lineup_simulator(request, team_id):
    team = get_object_or_404(Team, id=team_id)
    team_member = get_object_or_404(TeamMember, team=team, user=request.user, is_active=True)
    
    # Get current season
    current_season = Season.objects.filter(team=team, is_active=True).first()
    
    # Get all active players in the team
    players = TeamMember.objects.filter(
        team=team,
        is_active=True,
        teammemberprofile__active_player=True,
        role=TeamMember.Role.PLAYER
    ).select_related(
        'user',
        'teammemberprofile',
        'teammemberprofile__position'
    ).annotate(
        position_order=Case(
            When(teammemberprofile__position__type='GK', then=Value(1)),
            When(teammemberprofile__position__type='DEF', then=Value(2)),
            When(teammemberprofile__position__type='MID', then=Value(3)),
            When(teammemberprofile__position__type='ATT', then=Value(4)),
            default=Value(5),
            output_field=IntegerField(),
        )
    ).order_by(
        'position_order',
        'teammemberprofile__player_number'
    )
    
    context = {
        'team': team,
        'current_team': team,  # Add this for navbar
        'current_season': current_season,  # Add this for navbar
        'players': players,
        'is_team_admin': team_member.is_team_admin or team_member.role == TeamMember.Role.MANAGER,  # Changed is_admin to is_team_admin
    }
    return render(request, 'teams/lineup_simulator.html', context)

@login_required
def season_stats(request, team_id, season_id):
    team = get_object_or_404(Team, id=team_id)
    season = get_object_or_404(Season, id=season_id, team=team)
    team_member = get_object_or_404(TeamMember, team=team, user=request.user, is_active=True)
    
    # Get all active players in the team
    players = TeamMember.objects.filter(
        team=team,
        is_active=True,
        teammemberprofile__active_player=True,
        role=TeamMember.Role.PLAYER
    ).select_related(
        'user',
        'teammemberprofile',
        'teammemberprofile__position'
    ).annotate(
        position_order=Case(
            When(teammemberprofile__position__type='GK', then=Value(1)),
            When(teammemberprofile__position__type='DEF', then=Value(2)),
            When(teammemberprofile__position__type='MID', then=Value(3)),
            When(teammemberprofile__position__type='ATT', then=Value(4)),
            default=Value(5),
            output_field=IntegerField(),
        )
    ).order_by(
        'position_order',
        'teammemberprofile__player_number'
    )
    
    # Get stats for each player
    stats_dict = {}
    for player in players:
        stats_dict[player.id] = PlayerMatchStats.get_player_totals(player, season)
    
    context = {
        'team': team,
        'season': season,
        'players': players,
        'stats': stats_dict,
        'is_admin': team_member.is_team_admin or team_member.role == TeamMember.Role.MANAGER,
        'current_team': team,  # Add for navbar consistency
        'current_season': season,  # Add for navbar consistency
        'is_team_admin': team_member.is_team_admin or team_member.role == TeamMember.Role.MANAGER  # Add for navbar consistency
    }
    
    return render(request, 'teams/season_stats.html', context)

@login_required
def user_payments(request, team_id, season_id):
    team = get_object_or_404(Team, id=team_id)
    season = get_object_or_404(Season, id=season_id)
    team_member = get_object_or_404(TeamMember, team=team, user=request.user, is_active=True)
    
    # Get all payments for the current user, including verified ones
    all_payments = PlayerPayment.objects.filter(
        player__user=request.user,
        player__team=team,
        payment__season=season,
        amount__gt=0
    ).select_related('payment').annotate(
        total_players=models.Count(
            'payment__player_payments',
            filter=models.Q(payment__player_payments__amount__gt=0)
        ),
        verified_players=models.Count(
            'payment__player_payments',
            filter=models.Q(payment__player_payments__amount__gt=0, payment__player_payments__admin_verified=True)
        ),
        verification_percentage=models.Case(
            When(total_players__gt=0,
                 then=models.ExpressionWrapper(
                     100.0 * models.F('verified_players') / models.F('total_players'),
                     output_field=models.FloatField()
                 )),
            default=Value(0.0),
            output_field=models.FloatField(),
        )
    ).order_by('-payment__due_date')
    
    context = {
        'team': team,
        'current_team': team,
        'season': season,
        'current_season': season,
        'all_payments': all_payments,
        'today': timezone.now().date().isoformat(),
        'is_team_admin': team_member.is_team_admin
    }
    
    return render(request, 'teams/user_payments.html', context)

@login_required
def send_payment_reminder(request, team_id, season_id, payment_id):
    try:
        team = get_object_or_404(Team, id=team_id)
        if not is_user_team_admin(request.user, team):
            messages.error(request, "You don't have permission to send payment reminders.")
            return redirect('teams:payment_list', team_id=team_id, season_id=season_id)

        payment = get_object_or_404(Payment, id=payment_id, season_id=season_id)
        pending_payments = PlayerPayment.objects.filter(
            payment=payment,
            amount__gt=0,
            admin_verified=False
        ).select_related('player__user', 'player__user__profile')

        if not pending_payments.exists():
            messages.info(request, "No pending payments to remind about.")
            return redirect('teams:payment_list', team_id=team_id, season_id=season_id)

        current_site = get_current_site(request)
        protocol = 'https' if request.is_secure() else 'http'
        today = timezone.now().date()

        for player_payment in pending_payments:
            if not player_payment.player.user.email:
                continue

            context = {
                'player': player_payment.player.user,
                'team': team,
                'payment': payment,
                'amount': player_payment.amount,
                'domain': current_site.domain,
                'protocol': protocol,
                'today': today,
            }

            subject = f"Payment Reminder - {payment.name}"
            html_message = render_to_string('teams/email/payment_reminder.html', context)
            plain_message = strip_tags(html_message)

            try:
                send_mail(
                    subject,
                    plain_message,
                    settings.DEFAULT_FROM_EMAIL,
                    [player_payment.player.user.email],
                    html_message=html_message,
                    fail_silently=False,
                )
            except Exception as e:
                log_error(
                    e,
                    error_message=f"Failed to send payment reminder email to {player_payment.player.user.email}",
                    error_type="EmailError",
                    extra_context={
                        "team_id": team_id,
                        "payment_id": payment_id,
                        "user_id": player_payment.player.user.id
                    }
                )

        messages.success(request, "Payment reminders have been sent successfully.")
        return redirect('teams:payment_list', team_id=team_id, season_id=season_id)

    except Exception as e:
        log_error(
            e,
            error_message="Error sending payment reminders",
            error_type="PaymentReminderError",
            extra_context={
                "team_id": team_id,
                "payment_id": payment_id
            }
        )
        messages.error(request, "There was an error sending the payment reminders.")
        return redirect('teams:payment_list', team_id=team_id, season_id=season_id)

class CustomLoginView(auth_views.LoginView):
    def get(self, request, *args, **kwargs):
        """Store invitation token in session if present in URL."""
        invitation_token = request.GET.get('invitation_token') or request.GET.get('token')
        if invitation_token:
            request.session['pending_invitation_token'] = invitation_token
        return super().get(request, *args, **kwargs)

    def form_valid(self, form):
        """Security check complete. Log the user in."""
        print("\033[95m" + "="*50)  # Magenta separator
        print("\033[94m=== LOGIN PROCESS STARTED ===")  # Blue text
        print("\033[92m>> User attempting login: " + form.cleaned_data.get('username'))  # Green text
        print(">> Remember me checked: " + str(form.cleaned_data.get('remember_me', False)))
        print(">> Session ID before login: " + str(self.request.session.session_key))
        print("\033[0m")  # Reset color
        
        try:
            remember_me = form.cleaned_data.get('remember_me', False)
            print("\033[96m>> Calling parent's form_valid...")  # Cyan text
            response = super().form_valid(form)
            print(">> Parent form_valid completed successfully")
            print(">> User authenticated: " + str(self.request.user.is_authenticated))
            print(">> Session ID after auth: " + str(self.request.session.session_key))
            print("\033[0m")  # Reset color
            
            try:
                print("\033[93m>> Setting session expiry...")  # Yellow text
                if not remember_me:
                    print(">> Remember me is False - Session will expire when browser closes")
                    self.request.session.set_expiry(0)
                else:
                    print(">> Remember me is True - Session will expire in 24 hours")
                    self.request.session.set_expiry(24 * 60 * 60)
                
                # Check for pending invitation
                invitation_token = self.request.session.pop('pending_invitation_token', None)
                if invitation_token:
                    print(f"\033[92m>> Found pending invitation token: {invitation_token}")
                    return redirect(f'/accept-invitation/?token={invitation_token}')
                
                # If no invitation, proceed with normal login flow
                first_team = TeamMember.objects.filter(
                    user=self.request.user,
                    is_active=True
                ).order_by('team__id').first()
                
                if first_team:
                    self.request.session['current_team'] = first_team.team_id
                    print(f"\033[92m>> Automatically selected team: {first_team.team.name} (ID: {first_team.team_id})")
                
                print("\n\033[92m>> Final session state:")  # Green text
                print(">> - Session expiry age: " + str(self.request.session.get_expiry_age()))
                print(">> - Expires at browser close: " + str(self.request.session.get_expire_at_browser_close()))
                print(">> - Session modified: " + str(self.request.session.modified))
                print(">> - Selected team ID: " + str(self.request.session.get('current_team')))
                print("\033[94m=== LOGIN PROCESS COMPLETED ===")  # Blue text
                print("\033[95m" + "="*50 + "\033[0m\n")  # Magenta separator
                
                return response
                
            except Exception as session_error:
                print("\n\033[91m!!! ERROR SETTING SESSION EXPIRY !!!")  # Red text
                print(">> Error type: " + type(session_error).__name__)
                print(">> Error message: " + str(session_error))
                print("\n>> Session state when error occurred:")
                print(">> - Session exists: " + str(hasattr(self.request, 'session')))
                print(">> - Session ID: " + str(self.request.session.session_key))
                print(">> - Session modified: " + str(self.request.session.modified))
                print("\033[95m" + "="*50 + "\033[0m\n")  # Magenta separator
                raise
                
        except Exception as e:
            print("\n\033[91m!!! ERROR IN LOGIN PROCESS !!!")  # Red text
            print(">> Error type: " + type(e).__name__)
            print(">> Error message: " + str(e))
            print("\033[95m" + "="*50 + "\033[0m\n")  # Magenta separator
            raise

    def form_invalid(self, form):
        """Log failed login attempts and return the invalid form."""
        print("\n\033[95m" + "="*50)  # Magenta separator
        print("\033[91m=== LOGIN VALIDATION FAILED ===")  # Red text
        attempted_username = self.request.POST.get('username', '')
        print("\033[93m>> Attempted login for user: " + attempted_username)  # Yellow text
        print(">> Form errors: " + str(dict(form.errors)))
        print("\033[91m=== END OF FAILED LOGIN ===")  # Red text
        print("\033[95m" + "="*50 + "\033[0m\n")  # Magenta separator
        
        log_error(
            self.request,
            error_message="Login attempt failed",
            error_type="AuthenticationError",
            extra_context={
                "errors": dict(form.errors),
                "attempted_username": attempted_username
            }
        )
        return super().form_invalid(form)

@login_required
def delete_member(request, team_id, user_id):
    team = get_object_or_404(Team, id=team_id)
    member_to_delete = get_object_or_404(User, id=user_id)
    team_member = get_object_or_404(TeamMember, team=team, user=member_to_delete)
    
    # Check if the requesting user is a team admin
    requester_member = get_object_or_404(TeamMember, team=team, user=request.user, is_active=True)
    if not requester_member.is_team_admin:
        return HttpResponseForbidden("You don't have permission to delete team members.")
    
    # Don't allow admins to delete themselves
    if member_to_delete == request.user:
        messages.error(request, "You cannot delete yourself from the team.")
        return redirect('teams:team_members', team_id=team.id)
    
    try:
        with transaction.atomic():
            # Delete all team-specific data
            
            # Delete the team member profile
            TeamMemberProfile.objects.filter(team_member=team_member).delete()
            
            # Delete player payments for this team
            PlayerPayment.objects.filter(
                player=team_member,
                payment__season__team=team
            ).delete()
            
            # Delete player match stats for this team
            PlayerMatchStats.objects.filter(
                player=team_member,
                match__season__team=team
            ).delete()
            
            # Finally, delete the team member
            team_member.delete()
            
            messages.success(request, f"{member_to_delete.get_full_name()} has been removed from the team.")
    except Exception as e:
        log_error(
            request=request,
            error_message=f"Failed to delete team member: {str(e)}",
            error_type="DeletionError",
            extra_context={
                "team_id": team_id,
                "user_id": user_id,
                "error": str(e),
                "traceback": traceback.format_exc()
            }
        )
        messages.error(request, f"An error occurred while removing the member: {str(e)}")
    
    return redirect('teams:team_members', team_id=team.id)

@login_required
def accept_invitation(request):
    token = request.GET.get('token')
    
    # Log initial state
    log_error(
        request=request,
        error_message="Starting invitation acceptance process",
        error_type="InvitationDebug",
        extra_context={
            "token": token,
            "user_email": request.user.email,
            "session_keys": list(request.session.keys()),
            "relevant_session_data": {
                k: v for k, v in request.session.items() 
                if k.startswith('invite_')
            }
        }
    )
    
    try:
        team_member = TeamMember.objects.get(invitation_token=token, is_active=False)
        
        # Log team member state
        log_error(
            request=request,
            error_message="Found team member for invitation",
            error_type="InvitationDebug",
            extra_context={
                "team_member_id": team_member.id,
                "team_id": team_member.team_id,
                "email_match": team_member.email.lower() == request.user.email.lower(),
                "current_state": {
                    "is_active": team_member.is_active,
                    "invitation_accepted": team_member.invitation_accepted,
                    "has_profile": hasattr(team_member, 'teammemberprofile'),
                    "is_official": team_member.is_official,
                    "active_player": team_member.active_player
                }
            }
        )
        
        try:
            with transaction.atomic():
                # Log pre-update state
                log_error(
                    request=request,
                    error_message="Pre-update state",
                    error_type="InvitationDebug",
                    extra_context={
                        "member_data": {
                            "is_official": team_member.is_official,
                            "active_player": team_member.active_player
                        }
                    }
                )
                
                # Only create profile if one doesn't exist
                if not hasattr(team_member, 'teammemberprofile'):
                    # Log profile creation attempt
                    log_error(
                        request=request,
                        error_message="Attempting to create team member profile",
                        error_type="InvitationDebug",
                        extra_context={
                            "profile_data": {
                                "team_member_id": team_member.id,
                                "is_official": team_member.is_official,
                                "active_player": team_member.active_player,
                                "level": 1,
                                "condition": 'NORMAL'
                            }
                        }
                    )
                    
                    # Create team member profile
                    profile = TeamMemberProfile.objects.create(
                        team_member=team_member,
                        is_official=team_member.is_official,
                        active_player=team_member.active_player,
                        level=1,
                        condition='NORMAL'
                    )
                    
                    # Verify profile creation
                    log_error(
                        request=request,
                        error_message="Profile creation result",
                        error_type="InvitationDebug",
                        extra_context={
                            "profile_id": profile.id,
                            "profile_state": {
                                "team_member_id": profile.team_member_id,
                                "is_official": profile.is_official,
                                "active_player": profile.active_player,
                                "level": profile.level,
                                "condition": profile.condition
                            }
                        }
                    )
                
                # Activate the membership
                team_member.user = request.user  # Set the user
                team_member.is_active = True
                team_member.invitation_accepted = True
                team_member.invitation_token = None
                team_member.save()
                
                messages.success(request, f'You have successfully joined {team_member.team.name}!')
                return redirect('teams:dashboard')
                
        except Exception as transaction_error:
            log_error(
                request=request,
                error_message="Transaction failed during invitation acceptance",
                error_type="InvitationError",
                extra_context={
                    "error": str(transaction_error),
                    "error_type": type(transaction_error).__name__,
                    "traceback": traceback.format_exc()
                }
            )
            raise
            
    except TeamMember.DoesNotExist:
        log_error(
            request=request,
            error_message="Invalid invitation token",
            error_type="InvitationError",
            extra_context={
                "token": token,
                "user_email": request.user.email
            }
        )
        messages.error(request, "Invalid or expired invitation link.")
        return redirect('teams:dashboard')
    except Exception as e:
        log_error(
            request=request,
            error_message="Unexpected error during invitation acceptance",
            error_type="InvitationError",
            extra_context={
                "token": token,
                "user_email": request.user.email,
                "error": str(e),
                "error_type": type(e).__name__,
                "traceback": traceback.format_exc()
            }
        )
        messages.error(request, "An error occurred while accepting the invitation.")
        return redirect('teams:dashboard')

@login_required
def match_delete(request, team_id, season_id, match_id):
    team = get_object_or_404(Team, id=team_id)
    season = get_object_or_404(Season, id=season_id, team=team)
    match = get_object_or_404(Match, id=match_id, season=season)
    team_member = get_object_or_404(TeamMember, team=team, user=request.user, is_active=True)
    
    # Check if user has permission to delete matches
    if not (team_member.is_team_admin or team_member.role == TeamMember.Role.MANAGER):
        return HttpResponseForbidden("You don't have permission to delete matches.")
    
    if request.method == 'POST':
        try:
            match.delete()
            messages.success(request, f'Match against {match.opponent} has been deleted.')
            return redirect('teams:season_detail', team_id=team.id, season_id=season.id)
        except Exception as e:
            log_error(
                request=request,
                error_message=f"Failed to delete match: {str(e)}",
                error_type="MatchDeletionError",
                extra_context={
                    "team_id": team_id,
                    "season_id": season_id,
                    "match_id": match_id,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "traceback": traceback.format_exc()
                }
            )
            messages.error(request, 'An error occurred while deleting the match.')
            return redirect('teams:match_edit', team_id=team.id, season_id=season.id, match_id=match.id)
    
    # If not POST, redirect to match edit page
    return redirect('teams:match_edit', team_id=team.id, season_id=season.id, match_id=match.id)

