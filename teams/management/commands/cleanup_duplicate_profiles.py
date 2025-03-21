from django.core.management.base import BaseCommand
from django.db.models import Count
from teams.models import TeamMember, TeamMemberProfile
import logging

logger = logging.getLogger('django')

class Command(BaseCommand):
    help = 'Cleans up duplicate TeamMemberProfiles by keeping the most recently updated one'

    def handle(self, *args, **options):
        # Find team members with multiple profiles
        duplicate_profiles = (
            TeamMember.objects
            .annotate(profile_count=Count('teammemberprofile'))
            .filter(profile_count__gt=1)
        )

        self.stdout.write(f"Found {duplicate_profiles.count()} team members with duplicate profiles")

        for team_member in duplicate_profiles:
            try:
                # Get all profiles for this team member, ordered by last update
                profiles = TeamMemberProfile.objects.filter(team_member=team_member)
                
                # Log all profiles found
                self.stdout.write(f"\nTeam member: {team_member}")
                self.stdout.write(f"Found {profiles.count()} profiles:")
                for p in profiles:
                    self.stdout.write(f"- Profile {p.id}: active={p.active_player}, official={p.is_official}, level={p.level}")
                
                # Keep the profile with the highest ID (most recently created)
                profile_to_keep = profiles.order_by('-id').first()
                profiles_to_delete = profiles.exclude(id=profile_to_keep.id)
                
                self.stdout.write(f"\nKeeping profile {profile_to_keep.id}")
                self.stdout.write(f"Deleting {profiles_to_delete.count()} profiles: {list(profiles_to_delete.values_list('id', flat=True))}")
                
                # Delete other profiles
                profiles_to_delete.delete()
                
                self.stdout.write(self.style.SUCCESS(f"Successfully cleaned up profiles for {team_member}\n"))
                
            except Exception as e:
                logger.error(f"Error cleaning up profiles for team member {team_member}: {str(e)}")
                self.stdout.write(
                    self.style.ERROR(f"Error cleaning up profiles for {team_member}: {str(e)}")
                )

        self.stdout.write(self.style.SUCCESS("\nFinished cleaning up duplicate profiles")) 