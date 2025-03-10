from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import login
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.core.mail import send_mail
from django.urls import reverse, reverse_lazy
from django.utils.crypto import get_random_string
from django.http import HttpResponseForbidden
from django.db import transaction
from .models import Team, TeamMember, Season, Match
from .forms import (
    UserRegistrationForm, TeamMemberInviteForm, TeamForm, 
    EmailAuthenticationForm, AddTeamMemberForm, UserProfileForm,
    SeasonForm, MatchForm, AdminMemberProfileForm
)
from django.db import models
from django.contrib.auth.views import LogoutView
from django.utils import timezone

User = get_user_model()

def is_admin(user):
    return user.is_superuser

@login_required
def dashboard(request):
    team_memberships = TeamMember.objects.filter(user=request.user, is_active=True)
    current_team = request.session.get('current_team')
    
    if not current_team and team_memberships.exists():
        current_team = team_memberships.first().team.id
        request.session['current_team'] = current_team
    
    team_members = []
    current_membership = None
    current_season = None
    upcoming_matches = []
    
    if current_team:
        team_members = TeamMember.objects.filter(
            team_id=current_team
        ).filter(
            models.Q(is_active=True) | 
            models.Q(is_active=False, invitation_token__isnull=False)
        ).select_related('user', 'user__profile')
        
        current_membership = team_memberships.filter(team_id=current_team).first()
        
        # Get current season - first try to get the active season
        current_season = Season.objects.filter(
            team_id=current_team,
            is_active=True
        ).first()
        
        # If no active season, try to find a current season based on dates
        if not current_season:
            current_season = Season.objects.filter(
                team_id=current_team,
                start_date__lte=timezone.now().date(),
                end_date__gte=timezone.now().date()
            ).first()
            # If we found a current season by date, make it active
            if current_season:
                current_season.is_active = True
                current_season.save()
        
        if current_season:
            upcoming_matches = Match.objects.filter(
                season=current_season,
                match_date__gte=timezone.now().date()
            ).order_by('match_date', 'match_time')[:5]  # Show next 5 matches
    
    context = {
        'team_memberships': team_memberships,
        'current_team': current_team,
        'team_members': team_members,
        'current_membership': current_membership,
        'is_manager': current_membership and current_membership.role == TeamMember.Role.MANAGER,
        'is_team_admin': current_membership and current_membership.is_team_admin,
        'current_season': current_season,
        'upcoming_matches': upcoming_matches,
    }
    return render(request, 'teams/dashboard.html', context)

@login_required
def switch_team(request, team_id):
    team_member = get_object_or_404(TeamMember, team_id=team_id, user=request.user, is_active=True)
    request.session['current_team'] = team_id
    return redirect('dashboard')

class CustomLogoutView(LogoutView):
    next_page = reverse_lazy('login')

@login_required
def team_members(request, team_id):
    team = get_object_or_404(Team, id=team_id)
    team_member = get_object_or_404(TeamMember, team=team, user=request.user, is_active=True)
    
    # Get both active members and pending invitations
    members = TeamMember.objects.filter(
        team=team
    ).filter(
        models.Q(is_active=True) | 
        models.Q(is_active=False, invitation_token__isnull=False)
    ).select_related('user')
    
    context = {
        'team': team,
        'members': members,
        'is_manager': team_member.role == TeamMember.Role.MANAGER,
        'is_team_admin': team_member.is_team_admin,
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
                        reverse('register') + f'?token={invitation_token}'
                    )
                    send_mail(
                        f'Invitation to join {team.name}',
                        f'You have been invited to join {team.name} as a {role}. '
                        f'{"You will have team admin privileges. " if is_team_admin else ""}'
                        f'Click here to complete your registration: {invite_url}',
                        'from@example.com',
                        [email],
                        fail_silently=False,
                    )
                    
                    messages.success(request, f'Invitation sent to {email}')
                    return redirect('team_members', team_id=team.id)
                    
            except Exception as e:
                messages.error(request, f'Error sending invitation: {str(e)}')
                return redirect('team_members', team_id=team.id)
    else:
        form = TeamMemberInviteForm(team)
    
    return render(request, 'teams/invite_member.html', {'form': form, 'team': team})

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
    return redirect('team_members', team_id=team.id)

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
        return redirect('team_members', team_id=team.id)
    
    # Clear member data and set as inactive
    target_member.is_active = False
    target_member.invitation_accepted = False
    target_member.invitation_token = None
    target_member.is_team_admin = False
    target_member.save()
    
    messages.success(request, f'{target_member.user.get_full_name()} has been removed from the team.')
    return redirect('team_members', team_id=team.id)

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
    return redirect('team_members', team_id=team.id)

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
        form = UserRegistrationForm(request.POST, email=team_member.email)
        if form.is_valid():
            user = form.save(commit=False)
            user.email = team_member.email  # Ensure the email is set correctly
            user.save()
            
            team_member.user = user
            team_member.is_active = True
            team_member.invitation_accepted = True
            team_member.save()
            
            login(request, user)
            messages.success(request, f'Registration successful! You are now a member of {team_member.team.name}.')
            return redirect('dashboard')
    else:
        form = UserRegistrationForm(email=team_member.email)
    
    context = {
        'form': form,
        'team': team_member.team,
        'role': team_member.get_role_display(),
        'is_team_admin': team_member.is_team_admin,
        'email': team_member.email,
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
            return redirect('admin_teams')
    else:
        form = TeamForm()
    
    return render(request, 'teams/create_team.html', {'form': form})

@user_passes_test(is_admin)
def delete_team(request, team_id):
    team = get_object_or_404(Team, id=team_id)
    if request.method == 'POST':
        team.delete()
        messages.success(request, f'Team "{team.name}" has been deleted successfully!')
        return redirect('admin_teams')
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
            return redirect('dashboard')
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
                    return redirect('team_members', team_id=team.id)
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
        form = UserProfileForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Your profile has been updated successfully!')
            return redirect('dashboard')
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
    )
    
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
            return redirect('season_detail', team_id=team.id, season_id=season.id)
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
            return redirect('season_detail', team_id=team.id, season_id=season.id)
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
            return redirect('season_detail', team_id=team.id, season_id=season.id)
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
            return redirect('season_detail', team_id=team.id, season_id=season.id)
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
        form = AdminMemberProfileForm(request.POST, instance=member_to_edit)
        if form.is_valid():
            form.save()
            messages.success(request, f"{member_to_edit.get_full_name()}'s profile has been updated successfully!")
            return redirect('dashboard')
    else:
        form = AdminMemberProfileForm(instance=member_to_edit)
    
    return render(request, 'teams/edit_member.html', {
        'form': form,
        'team': team,
        'member': member_to_edit
    })
