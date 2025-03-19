from django.core.exceptions import ObjectDoesNotExist
from ..models import Team, TeamMember

def get_current_team(user):
    """
    Get the current team for a user based on their session or default to their first active team.
    """
    try:
        # Try to get the team from the user's session
        if hasattr(user, 'session') and user.session.get('current_team_id'):
            team = Team.objects.get(id=user.session['current_team_id'])
            if TeamMember.objects.filter(team=team, user=user, is_active=True).exists():
                return team
        
        # If no team in session or team not found, get first active team membership
        team_member = TeamMember.objects.filter(user=user, is_active=True).first()
        if team_member:
            return team_member.team
    except (ObjectDoesNotExist, AttributeError):
        pass
    
    return None 