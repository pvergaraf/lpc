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
        return redirect('teams:login')

    # Attach request to user for session access
    request.user.request = request
    current_team = get_current_team(request.user)
    
    if not current_team:
        messages.warning(request, "You are not a member of any team. Please join or create a team.")
        return redirect('teams:team_list')

    try:
        # Get the user's team membership
        team_member = TeamMember.objects.get(
            team=current_team,
            user=request.user,
            is_active=True
        )
    except TeamMember.DoesNotExist:
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

    # Get team memberships for the teams list
    team_memberships = TeamMember.objects.filter(
        user=request.user,
        is_active=True
    ).select_related('team')

    # Get team members for the current team
    team_members = TeamMember.objects.filter(
        team=current_team
    ).filter(
        models.Q(is_active=True) | 
        models.Q(is_active=False, invitation_token__isnull=False)
    ).select_related('user', 'user__profile')

    # Get upcoming matches if there's a current season
    upcoming_matches = None
    if current_season:
        upcoming_matches = Match.objects.filter(
            season=current_season,
            match_date__gte=today
        ).order_by('match_date', 'match_time')

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

    return render(request, 'teams/dashboard.html', context)

@login_required
def switch_team(request, team_id):
    team_member = get_object_or_404(TeamMember, team_id=team_id, user=request.user, is_active=True)
    request.session['current_team'] = team_id
    return redirect('teams:dashboard')

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
    team = get_object_or_404(Team, id=team_id)
    team_member = get_object_or_404(TeamMember, team=team, user=request.user, is_active=True)
    
    # Get active members
    active_members = TeamMember.objects.filter(
        team=team,
        is_active=True
    ).select_related('user', 'user__profile')
    
    # Get pending invitations
    pending_invitations = TeamMember.objects.filter(
        team=team,
        is_active=False,
        invitation_token__isnull=False,
        invitation_accepted=False
    )
    
    context = {
        'team': team,
        'active_members': active_members,
        'pending_invitations': pending_invitations,
        'user': request.user,
        'user_is_admin': team_member.is_team_admin or team_member.role == TeamMember.Role.MANAGER
    }
    return render(request, 'teams/team_members.html', context)

@login_required
def invite_member(request, team_id):
    team = get_object_or_404(Team, id=team_id)
    team_member = get_object_or_404(TeamMember, team=team, user=request.user, is_active=True)
    
    # Check if user is team admin or manager
    if not (team_member.is_team_admin or team_member.role == TeamMember.Role.MANAGER):
        return HttpResponseForbidden("You don't have permission to invite members.")
    
    if request.method == 'POST':
        form = TeamMemberInviteForm(team, request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            role = form.cleaned_data['role']
            is_team_admin = form.cleaned_data['is_team_admin']
            is_official = form.cleaned_data['is_official']
            invitation_token = get_random_string(64)
            
            try:
                with transaction.atomic():
                    # Look for existing inactive member to update
                    existing_member = TeamMember.objects.filter(
                        team=team,
                        is_active=False
                    ).filter(
                        models.Q(email=email) | models.Q(user__email=email)
                    ).first()

                    if existing_member:
                        # Update existing record
                        existing_member.role = role
                        existing_member.is_team_admin = is_team_admin
                        existing_member.invitation_token = invitation_token
                        existing_member.invitation_accepted = False
                        existing_member.save()
                        team_member = existing_member
                    else:
                        # Create new inactive team member
                        team_member = TeamMember.objects.create(
                            team=team,
                            user=None,
                            email=email,
                            role=role,
                            is_team_admin=is_team_admin,
                            is_active=False,
                            invitation_token=invitation_token,
                            invitation_accepted=False
                        )
                    
                    # Send invitation email
                    invite_url = request.build_absolute_uri(
                        reverse('teams:register') + f'?token={invitation_token}'
                    )
                    
                    # Print invitation details to console for development
                    if settings.DEBUG:
                        print("\n=== Invitation Details ===")
                        print(f"Email: {email}")
                        print(f"Role: {role}")
                        print(f"Team Admin: {is_team_admin}")
                        print(f"Official Player: {is_official}")
                        print(f"Token: {invitation_token}")
                        print(f"URL: {invite_url}")
                        print("=======================\n")
                    
                    # Render the HTML email template
                    html_message = render_to_string('teams/email/team_invitation.html', {
                        'team': team,
                        'role': team_member.get_role_display(),
                        'is_team_admin': is_team_admin,
                        'is_official': is_official,
                        'invite_url': invite_url,
                    })
                    
                    # Send the email with both plain text and HTML versions
                    send_mail(
                        subject=f'Invitation to join {team.name}',
                        message=f'You have been invited to join {team.name} as a {team_member.get_role_display()}. Click here to accept: {invite_url}',
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[email],
                        html_message=html_message,
                        fail_silently=False,
                    )
                    
                    # Store is_official in the session for use during registration
                    request.session[f'invite_{invitation_token}_is_official'] = is_official
                    
                    messages.success(request, f'Invitation sent to {email}')
                    return redirect('teams:team_members', team_id=team.id)
                    
            except Exception as e:
                messages.error(request, f'Error sending invitation: {str(e)}')
                return redirect('teams:team_members', team_id=team.id)
    else:
        form = TeamMemberInviteForm(team)
    
    return render(request, 'teams/invite_member.html', {
        'form': form,
        'team': team
    })

@login_required
def toggle_team_admin(request, team_id, member_id):
    team = get_object_or_404(Team, id=team_id)
    requesting_member = get_object_or_404(TeamMember, team=team, user=request.user, is_active=True)
    target_member = get_object_or_404(TeamMember, id=member_id, team=team, is_active=True)
    
    # Check if user has permission to modify team admin status
    if not (requesting_member.is_team_admin or requesting_member.role == TeamMember.Role.MANAGER):
        return HttpResponseForbidden("You don't have permission to modify team admin status.")
    
    target_member.is_team_admin = not target_member.is_team_admin
    target_member.save()
    
    messages.success(
        request,
        f'{target_member.user.get_full_name()} is {"now" if target_member.is_team_admin else "no longer"} a team admin.'
    )
    return redirect('teams:team_members', team_id=team.id)

@login_required
def remove_member(request, team_id, member_id):
    team = get_object_or_404(Team, id=team_id)
    requesting_member = get_object_or_404(TeamMember, team=team, user=request.user, is_active=True)
    target_member = get_object_or_404(TeamMember, id=member_id, team=team, is_active=True)
    
    # Check if user has permission to remove members
    if not (requesting_member.is_team_admin or requesting_member.role == TeamMember.Role.MANAGER):
        return HttpResponseForbidden("You don't have permission to remove team members.")
    
    # Don't allow removing yourself
    if target_member.user == request.user:
        messages.error(request, "You cannot remove yourself from the team.")
        return redirect('teams:team_members', team_id=team.id)
    
    # Clear member data and set as inactive
    target_member.is_active = False
    target_member.invitation_accepted = False
    target_member.invitation_token = None
    target_member.is_team_admin = False
    target_member.save()
    
    messages.success(request, f'{target_member.user.get_full_name()} has been removed from the team.')
    return redirect('teams:team_members', team_id=team.id)

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
        context = {
            'title': 'Invalid Invitation',
            'message': 'This invitation link is no longer active or has already been used.',
            'help_text': 'Please contact your team administrator for a new invitation.'
        }
        return render(request, 'teams/404.html', context, status=404)
    
    if request.method == 'POST':
        form = UserRegistrationForm(request.POST, request.FILES, email=team_member.email)
        if form.is_valid():
            try:
                with transaction.atomic():
                    # Try to get existing user or create new one
                    user = User.objects.filter(email=team_member.email).first()
                    if user:
                        # Update existing user
                        user.first_name = form.cleaned_data['first_name']
                        user.last_name = form.cleaned_data['last_name']
                        user.save()
                    else:
                        # Create new user
                        user = form.save(commit=False)
                        user.username = team_member.email
                        user.email = team_member.email
                        user.save()

                    # Get the is_official status from session
                    is_official = request.session.get(f'invite_{token}_is_official', False)
                    
                    # Create or update profile
                    profile = Profile.objects.get_or_create(user=user)[0]
                    profile.player_number = form.cleaned_data['player_number']
                    profile.position = form.cleaned_data['position']
                    profile.is_official = is_official
                    profile.date_of_birth = form.cleaned_data['date_of_birth']
                    if form.cleaned_data.get('profile_picture'):
                        profile.profile_picture = form.cleaned_data['profile_picture']
                    profile.save()

                    # Update team member
                    team_member.user = user
                    team_member.is_active = True
                    team_member.invitation_accepted = True
                    team_member.save()

                    # Clean up the session
                    request.session.pop(f'invite_{token}_is_official', None)

                    # Log in the user
                    login(request, user)
                    messages.success(request, f'Registration successful! You are now a member of {team_member.team.name}.')
                    return redirect('teams:dashboard')

            except Exception as e:
                if settings.DEBUG:
                    messages.error(request, 'An error occurred during registration.')
                else:
                    messages.error(request, 'An error occurred during registration. Please try again.')
        else:
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
    
    context = {
        'form': form,
        'team': team_member.team,
        'role': team_member.get_role_display(),
        'is_team_admin': team_member.is_team_admin,
        'is_official': is_official,
        'email': team_member.email,
        'image_url': 'https://raw.githubusercontent.com/pabloveintimilla/club/main/teams/static/teams/images/felicidades.png'
    }
    return render(request, 'teams/register.html', context)

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
            user = form.save()
            # Handle profile picture clearing
            profile = getattr(user, 'profile', None)
            if profile:
                if request.POST.get('profile_picture-clear'):
                    profile.profile_picture = 'profile_pics/castolo.png'  # Reset to default
                    profile.save()
            messages.success(request, 'Your profile has been updated successfully!')
            return redirect('teams:dashboard')
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
        return HttpResponseForbidden("You don't have permission to create matches.")
    
    if request.method == 'POST':
        form = MatchForm(request.POST, season=season)
        if form.is_valid():
            match = form.save(commit=False)
            match.season = season
            match.save()
            messages.success(request, f'Match against {match.opponent} has been scheduled.')
            return redirect('teams:season_detail', team_id=team.id, season_id=season.id)
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
    
    # Check if the requesting user is a team admin
    requester_member = get_object_or_404(TeamMember, team=team, user=request.user)
    if not requester_member.is_team_admin:
        return HttpResponseForbidden("You don't have permission to edit member profiles.")
    
    if request.method == 'POST':
        form = AdminMemberProfileForm(request.POST, request.FILES, instance=member_to_edit)
        if form.is_valid():
            user = form.save()
            # Handle profile picture clearing
            profile = getattr(user, 'profile', None)
            if profile:
                if request.POST.get('profile_picture-clear'):
                    profile.profile_picture = 'profile_pics/castolo.png'  # Reset to default
                    profile.save()
            messages.success(request, f"{member_to_edit.get_full_name()}'s profile has been updated successfully!")
            return redirect('teams:dashboard')
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
        return HttpResponseForbidden("You don't have permission to create payments.")

    if request.method == 'POST':
        form = PaymentForm(request.POST)
        if form.is_valid():
            payment = form.save(commit=False)
            payment.season = season
            payment.save()
            
            # Create player payments for all official players
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
                    amount=0  # Default amount, to be edited by admin
                )
            
            messages.success(request, 'Payment created successfully.')
            return redirect('teams:payment_edit', team_id=team.id, season_id=season.id, payment_id=payment.id)
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
    team_memberships = TeamMember.objects.filter(
        user=request.user,
        is_active=True
    ).select_related('team')
    
    return render(request, 'teams/team_list.html', {
        'team_memberships': team_memberships
    })

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
