from django.core.management.base import BaseCommand
from teams.models import Team, TeamMember, TeamMemberProfile
from django.db import transaction

class Command(BaseCommand):
    help = 'Shows team member data status'

    def handle(self, *args, **options):
        try:
            with transaction.atomic():
                # Get team with ID 1
                target_team = Team.objects.get(id=1)
                self.stdout.write(f'Target team: {target_team.name}\n')

                # Get all team members
                team_members = TeamMember.objects.filter(team_id=1).select_related('teammemberprofile')
                self.stdout.write(f'Found {team_members.count()} team members\n')

                self.stdout.write('Member Status:')
                self.stdout.write('=' * 80)
                self.stdout.write(f'{"Email":<30} {"is_official":<12} {"active_player":<15} {"Has Profile":<12}')
                self.stdout.write('-' * 80)

                null_is_official = 0
                null_active_player = 0
                null_email = 0

                for member in team_members:
                    email = member.email if member.email else "NO EMAIL"
                    email = email[:28] + '..' if len(email) > 30 else email
                    is_official = getattr(member, 'is_official', None)
                    active_player = getattr(member, 'active_player', None)
                    has_profile = hasattr(member, 'teammemberprofile')

                    if is_official is None:
                        null_is_official += 1
                    if active_player is None:
                        null_active_player += 1
                    if not member.email:
                        null_email += 1

                    self.stdout.write(
                        f'{email:<30} {str(is_official):<12} {str(active_player):<15} {str(has_profile):<12}'
                    )

                self.stdout.write('=' * 80)
                self.stdout.write(f'\nSummary:')
                self.stdout.write(f'Total members: {team_members.count()}')
                self.stdout.write(f'Members with null is_official: {null_is_official}')
                self.stdout.write(f'Members with null active_player: {null_active_player}')
                self.stdout.write(f'Members with null email: {null_email}')

        except Team.DoesNotExist:
            self.stdout.write(self.style.ERROR('Team with ID 1 does not exist'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'An error occurred: {str(e)}'))