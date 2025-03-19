from django.core.management.base import BaseCommand
from teams.models import Team, TeamMember
from django.db import transaction

class Command(BaseCommand):
    help = 'Migrates all team members to team ID 1'

    def handle(self, *args, **options):
        try:
            with transaction.atomic():
                # Get team with ID 1
                target_team = Team.objects.get(id=1)
                self.stdout.write(f'Target team: {target_team.name}')

                # Show all teams and their member counts
                all_teams = Team.objects.all()
                self.stdout.write('\nCurrent team distribution:')
                for team in all_teams:
                    member_count = TeamMember.objects.filter(team=team).count()
                    self.stdout.write(f'Team {team.id} ({team.name}): {member_count} members')

                # Get all team members that are not in team 1
                team_members = TeamMember.objects.exclude(team_id=1)
                self.stdout.write(f'\nFound {team_members.count()} team members to move')

                # Show details of members to be moved
                for member in team_members:
                    old_team_id = member.team_id
                    self.stdout.write(f'Moving member {member.email} from team {old_team_id} to team 1')
                    member.team = target_team
                    member.save()

                # Show final distribution
                self.stdout.write('\nFinal team distribution:')
                for team in all_teams:
                    member_count = TeamMember.objects.filter(team=team).count()
                    self.stdout.write(f'Team {team.id} ({team.name}): {member_count} members')

                self.stdout.write(self.style.SUCCESS('\nSuccessfully migrated all team members to team ID 1'))

        except Team.DoesNotExist:
            self.stdout.write(self.style.ERROR('Team with ID 1 does not exist'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'An error occurred: {str(e)}'))