from django.core.exceptions import ObjectDoesNotExist
from ..models import Team, TeamMember

def get_current_team(user):
    """
    Get the current team for a user based on their session or default to their first active team.
    """
    try:
        # Try to get the team from the user's session
        if hasattr(user, 'request') and user.request.session.get('current_team'):
            team = Team.objects.get(id=user.request.session['current_team'])
            if TeamMember.objects.filter(team=team, user=user, is_active=True).exists():
                return team
        
        # If no team in session or team not found, get first active team membership
        team_member = TeamMember.objects.filter(user=user, is_active=True).first()
        if team_member:
            if hasattr(user, 'request'):
                user.request.session['current_team'] = team_member.team.id
            return team_member.team
    except (ObjectDoesNotExist, AttributeError):
        pass
    
    return None 