from django.core.management.base import BaseCommand
from teams.models import Team, TeamMember, TeamMemberProfile
from django.db import transaction

class Command(BaseCommand):
    help = 'Migrates all team members and profiles to team ID 1'

    def handle(self, *args, **options):
        try:
            with transaction.atomic():
                # Get team with ID 1
                target_team = Team.objects.get(id=1)
                self.stdout.write(f'Target team: {target_team.name}')

                # Get all team members
                team_members = TeamMember.objects.all()
                self.stdout.write(f'Found {team_members.count()} team members')

                # Update each team member
                for member in team_members:
                    old_team = member.team
                    member.team = target_team
                    member.save()
                    self.stdout.write(f'Moved member {member.email} from team {old_team.name} to {target_team.name}')

                self.stdout.write(self.style.SUCCESS('Successfully migrated all team members to team ID 1'))

        except Team.DoesNotExist:
            self.stdout.write(self.style.ERROR('Team with ID 1 does not exist'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'An error occurred: {str(e)}')) 