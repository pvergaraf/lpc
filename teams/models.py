from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.utils.translation import gettext_lazy as _
from django.core.validators import MinValueValidator, MaxValueValidator
from PIL import Image
import os
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone
from .utils.logging_utils import log_error
import traceback
import logging
from django.core.exceptions import ValidationError
from django.db.models import Count, Sum, Q

class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('The Email field must be set')
        email = self.normalize_email(email.lower())  # Force lowercase
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(email, password, **extra_fields)

class User(AbstractUser):
    username = None  # Remove username field
    email = models.EmailField(_('email address'), unique=True)
    date_of_birth = models.DateField(null=True, blank=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name']

    objects = CustomUserManager()

    def __str__(self):
        return self.email

class Position(models.Model):
    POSITION_TYPES = [
        ('GK', 'Goalkeeper'),
        ('DEF', 'Defense'),
        ('MID', 'Midfield'),
        ('ATT', 'Attack')
    ]

    POSITIONS = [
        # Goalkeeper
        ('GK', 'Goalkeeper'),
        # Defense
        ('SW', 'Sweeper'),
        ('CB', 'Center Back'),
        ('LB', 'Left Back'),
        ('RB', 'Right Back'),
        ('LWB', 'Left Wing Back'),
        ('RWB', 'Right Wing Back'),
        # Midfield
        ('DM', 'Defensive Midfielder'),
        ('CM', 'Central Midfielder'),
        ('WM', 'Wing Midfielder'),
        ('LM', 'Left Midfielder'),
        ('RM', 'Right Midfielder'),
        ('AM', 'Attacking Midfielder'),
        # Attack
        ('LW', 'Left Winger'),
        ('RW', 'Right Winger'),
        ('SS', 'Second Striker'),
        ('CF', 'Center Forward'),
        ('ST', 'Striker'),
        ('LF', 'Left Forward'),
        ('RF', 'Right Forward'),
    ]

    code = models.CharField(max_length=3, choices=POSITIONS, unique=True)
    name = models.CharField(max_length=50)
    type = models.CharField(max_length=3, choices=POSITION_TYPES)
    
    def __str__(self):
        return f"{self.code} - {self.name}"

    @property
    def color(self):
        return {
            'GK': '#FFD700',  # Gold for Goalkeeper
            'DEF': '#32CD32', # Lime Green for Defense
            'MID': '#4169E1', # Royal Blue for Midfield
            'ATT': '#FF4500', # Orange Red for Attack
        }.get(self.type, '#808080')  # Gray as default

class Profile(models.Model):
    """Global user profile with data shared across all teams"""
    COUNTRIES = [
        ('CL', 'Chile'),  # Chile first
        ('AR', 'Argentina'),
        ('BO', 'Bolivia'),
        ('BR', 'Brazil'),
        ('CO', 'Colombia'),
        ('EC', 'Ecuador'),
        ('PE', 'Peru'),
        ('PY', 'Paraguay'),
        ('UY', 'Uruguay'),
        ('VE', 'Venezuela'),
        ('DE', 'Germany'),
        ('ES', 'Spain'),
        ('FR', 'France'),
        ('GB', 'United Kingdom'),
        ('IT', 'Italy'),
        ('MX', 'Mexico'),
        ('NL', 'Netherlands'),
        ('PT', 'Portugal'),
        ('US', 'United States'),
    ]

    CONDITION_CHOICES = [
        ('TOP', 'Top Condition'),
        ('GOOD', 'Good Condition'),
        ('NORMAL', 'Normal Condition'),
        ('BAD', 'Bad Condition'),
        ('AWFUL', 'Awful Condition'),
        ('INJURED', 'Injured'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    date_of_birth = models.DateField(null=True, blank=True)
    rut = models.CharField(max_length=12, blank=True, null=True, help_text="Chilean ID number (RUT)")
    country = models.CharField(
        max_length=2,
        choices=COUNTRIES,
        default='CL',
        help_text="Player's country"
    )

    def __str__(self):
        return f"{self.user.get_full_name()}'s Profile"

class TeamMemberProfile(models.Model):
    """Team-specific profile data"""
    CONDITION_CHOICES = [
        ('TOP', 'Top Condition'),
        ('GOOD', 'Good Condition'),
        ('NORMAL', 'Normal Condition'),
        ('BAD', 'Bad Condition'),
        ('AWFUL', 'Awful Condition'),
        ('INJURED', 'Injured'),
    ]

    team_member = models.OneToOneField('TeamMember', on_delete=models.CASCADE)
    profile_picture = models.ImageField(
        upload_to='profile_pics/',
        default='profile_pics/castolo.png',
        blank=True
    )
    description = models.CharField(max_length=20, blank=True, help_text="A short description (max 20 characters)")
    player_number = models.IntegerField(null=True, blank=True)
    position = models.ForeignKey(Position, on_delete=models.SET_NULL, null=True, blank=True)
    level = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(99)],
        default=1
    )
    is_official = models.BooleanField(default=False, help_text="Indicates if the player is officially registered")
    active_player = models.BooleanField(default=True, help_text="Indicates if the player is currently active")
    condition = models.CharField(
        max_length=10,
        choices=CONDITION_CHOICES,
        default='NORMAL'
    )

    def __str__(self):
        return f"{self.team_member.user.get_full_name()}'s Profile in {self.team_member.team.name}"

    class Meta:
        unique_together = [('team_member', 'player_number')]  # Ensure numbers are unique within a team

class TeamMember(models.Model):
    """Represents a user's membership in a team with team-specific data"""
    class Role(models.TextChoices):
        PLAYER = 'PLAYER', 'Player'
        MANAGER = 'MANAGER', 'Manager'
    
    team = models.ForeignKey('Team', on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)  # For storing email before user registration
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.PLAYER)
    is_team_admin = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    invitation_token = models.CharField(max_length=64, null=True, blank=True, unique=True)
    invitation_accepted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # New fields for storing invitation settings
    is_official = models.BooleanField(default=False, help_text="Whether this member is an official player")
    active_player = models.BooleanField(default=True, help_text="Whether this member is an active player")

    def __str__(self):
        if self.user:
            return f"{self.user.get_full_name()} - {self.team.name}"
        return f"{self.email} (Invited) - {self.team.name}"

    def save(self, *args, **kwargs):
        logger = logging.getLogger('teams')
        try:
            logger.info(f"Saving TeamMember: user={self.user}, team={self.team}, role={self.role}")
            super().save(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error saving TeamMember: {str(e)}")
            logger.error(traceback.format_exc())
            raise

class Team(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    team_photo = models.ImageField(
        upload_to='team_photos/',
        default='team_photos/default.png',
        blank=True,
        help_text="Upload a square team photo"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        logger = logging.getLogger('teams')

        try:
            is_new = self.pk is None
            logger.info(f"Saving team {self.name} (ID: {self.pk})")
            logger.info(f"Team photo field: {self.team_photo}")
            
            if self.team_photo:
                logger.info(f"Team photo details - Name: {self.team_photo.name}, Size: {self.team_photo.size if hasattr(self.team_photo, 'size') else 'N/A'}")
            
            if not is_new and self.team_photo:
                try:
                    old_instance = Team.objects.get(pk=self.pk)
                    logger.info(f"Old team photo: {old_instance.team_photo.name if old_instance.team_photo else 'None'}")
                    logger.info(f"New team photo: {self.team_photo.name}")
                    
                    if (old_instance.team_photo and 
                        old_instance.team_photo != self.team_photo and 
                        old_instance.team_photo.name != 'team_photos/default.png'):
                        logger.info(f"Attempting to delete old team photo: {old_instance.team_photo.path}")
                        try:
                            old_instance.team_photo.delete(save=False)
                            logger.info("Successfully deleted old team photo")
                        except Exception as delete_error:
                            logger.error(f"Error deleting old team photo: {str(delete_error)}")
                except Team.DoesNotExist:
                    logger.warning(f"Could not find existing team with ID {self.pk}")
                except Exception as e:
                    logger.error(f"Error handling old team photo: {str(e)}")
                    logger.error(traceback.format_exc())

            super().save(*args, **kwargs)
            logger.info(f"Successfully saved team {self.name} to database")

            # Process the team photo if it exists and has changed
            if self.team_photo and (is_new or self.team_photo.name != 'team_photos/default.png'):
                try:
                    logger.info(f"Processing team photo: {self.team_photo.path}")
                    img = Image.open(self.team_photo.path)
                    logger.info(f"Image opened successfully. Format: {img.format}, Mode: {img.mode}, Size: {img.size}")
                    
                    # Convert to RGB if necessary
                    if img.mode != 'RGB':
                        logger.info(f"Converting image from {img.mode} to RGB")
                        img = img.convert('RGB')
                    
                    # Get the minimum dimension to make it square
                    min_dim = min(img.width, img.height)
                    logger.info(f"Cropping image to square with dimensions {min_dim}x{min_dim}")
                    
                    # Calculate cropping box
                    left = (img.width - min_dim) // 2
                    top = (img.height - min_dim) // 2
                    right = left + min_dim
                    bottom = top + min_dim
                    
                    # Crop to square
                    img = img.crop((left, top, right, bottom))
                    logger.info("Successfully cropped image to square")
                    
                    # Resize if larger than 300x300
                    if min_dim > 300:
                        logger.info("Resizing image to 300x300")
                        img = img.resize((300, 300), Image.Resampling.LANCZOS)
                    
                    # Save the processed image
                    logger.info(f"Saving processed image to {self.team_photo.path}")
                    img.save(self.team_photo.path, quality=90, optimize=True)
                    logger.info("Successfully saved processed image")
                    
                except Exception as e:
                    logger.error(f"Error processing team photo for team {self.name}: {str(e)}")
                    logger.error(f"Full traceback: {traceback.format_exc()}")
                    # If there's an error processing the image, set it to default
                    self.team_photo = 'team_photos/default.png'
                    logger.info("Setting team photo to default due to processing error")
                    super().save(update_fields=['team_photo'])
        except Exception as e:
            logger.error(f"Error saving team {self.name}: {str(e)}")
            logger.error(f"Full traceback: {traceback.format_exc()}")
            raise

    def get_upcoming_birthdays(self, days=15):
        """Get team members with birthdays in the next X days."""
        from datetime import date, timedelta
        from django.db.models import ExpressionWrapper, BooleanField
        from django.db.models.functions import ExtractMonth, ExtractDay

        today = date.today()
        end_date = today + timedelta(days=days)
        
        # Get all active team members with their profiles
        members = TeamMember.objects.filter(
            team=self,
            is_active=True,
            user__isnull=False,
            user__profile__date_of_birth__isnull=False
        ).select_related('user', 'user__profile')

        upcoming_birthdays = []
        for member in members:
            birth_date = member.user.profile.date_of_birth
            # Get this year's birthday
            this_year_bday = date(today.year, birth_date.month, birth_date.day)
            
            # If birthday has passed this year, use next year's date
            if this_year_bday < today:
                this_year_bday = date(today.year + 1, birth_date.month, birth_date.day)
            
            # Check if birthday is within range
            if today <= this_year_bday <= end_date:
                days_until = (this_year_bday - today).days
                upcoming_birthdays.append({
                    'member': member,
                    'birthday': this_year_bday,
                    'days_until': days_until,
                    'is_today': days_until == 0
                })
        
        # Sort by closest birthday
        return sorted(upcoming_birthdays, key=lambda x: x['days_until'])

    def __str__(self):
        return self.name

class Season(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='seasons')
    name = models.CharField(max_length=100)  # e.g., "Spring 2025"
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=True)
    slach_account = models.CharField(max_length=50, blank=True, null=True, help_text="Slach account for payment links (e.g. 'lpcfc')")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-start_date']
        unique_together = [('team', 'name')]

    def __str__(self):
        return f"{self.team.name} - {self.name}"

    def save(self, *args, **kwargs):
        if self.is_active:
            # Set all other seasons of this team to inactive
            Season.objects.filter(team=self.team).exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)

    @property
    def is_current(self):
        today = timezone.now().date()
        return self.start_date <= today <= self.end_date

class Match(models.Model):
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name='matches')
    opponent = models.CharField(max_length=100)
    match_date = models.DateField()
    match_time = models.TimeField(null=True, blank=True)
    field_number = models.PositiveIntegerField(null=True, blank=True, help_text="Enter the field number")
    is_home_game = models.BooleanField(default=True)
    home_score = models.PositiveIntegerField(null=True, blank=True)
    away_score = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    is_official = models.BooleanField(default=False, help_text="Indicates if this is an official match")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['match_date', 'match_time']
        verbose_name_plural = 'matches'

    def __str__(self):
        home_team = self.season.team.name if self.is_home_game else self.opponent
        away_team = self.opponent if self.is_home_game else self.season.team.name
        return f"{home_team} vs {away_team} - {self.match_date}"

    @property
    def played(self):
        return self.home_score is not None and self.away_score is not None

    @property
    def score_display(self):
        if not self.played:
            return "vs"
        return f"{self.home_score} - {self.away_score}"

    @property
    def team_score(self):
        """Return the team's score regardless of home/away."""
        if not self.played:
            return None
        return self.home_score if self.is_home_game else self.away_score
        
    @property
    def opponent_score(self):
        """Return the opponent's score regardless of home/away."""
        if not self.played:
            return None
        return self.away_score if self.is_home_game else self.home_score

class Payment(models.Model):
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name='payments')
    name = models.CharField(max_length=200)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    due_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['due_date']

    def __str__(self):
        return f"{self.name} - {self.season.name}"

class PlayerPayment(models.Model):
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name='player_payments')
    player = models.ForeignKey(TeamMember, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    is_paid = models.BooleanField(default=False)
    admin_verified = models.BooleanField(default=False)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['payment__due_date']
        unique_together = ['payment', 'player']

    def __str__(self):
        return f"{self.player.user.get_full_name()} - {self.payment.name}"

    def mark_as_paid(self, is_admin=False):
        self.is_paid = True
        if is_admin:
            self.admin_verified = True
        self.paid_at = timezone.now()
        self.save()

    def mark_as_unpaid(self, is_admin=False):
        """Mark a payment as unpaid."""
        self.is_paid = False
        self.admin_verified = False if is_admin else self.admin_verified
        self.paid_at = None
        self.save()

class PlayerMatchStats(models.Model):
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name='player_stats')
    player = models.ForeignKey(TeamMember, on_delete=models.CASCADE, related_name='match_stats')
    played = models.BooleanField(default=False)
    goals = models.PositiveIntegerField(default=0)
    assists = models.PositiveIntegerField(default=0)
    yellow_cards = models.PositiveIntegerField(default=0)
    red_cards = models.PositiveIntegerField(default=0)
    is_mvp = models.BooleanField(default=False, help_text="Indicates if the player was MVP of this match")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['match__match_date', 'match__match_time']
        unique_together = ['match', 'player']
        verbose_name_plural = 'Player match stats'

    def __str__(self):
        return f"{self.player.user.get_full_name()} - {self.match} Stats"

    @property
    def season(self):
        return self.match.season

    @classmethod
    def get_player_totals(cls, player, season=None):
        stats = cls.objects.filter(player=player)
        if season:
            stats = stats.filter(match__season=season)
        
        totals = stats.aggregate(
            matches_played=Count('id', filter=Q(played=True)),
            goals=Sum('goals'),
            assists=Sum('assists'),
            yellow_cards=Sum('yellow_cards'),
            red_cards=Sum('red_cards'),
            mvp_matches=Count('id', filter=Q(is_mvp=True))
        )
        
        # Replace None values with 0
        return {k: v or 0 for k, v in totals.items()}

@receiver(post_save, sender=TeamMember)
def create_team_member_profile(sender, instance, created, **kwargs):
    """Create a TeamMemberProfile when a TeamMember is created."""
    logger = logging.getLogger('teams')
    
    try:
        logger.info(f"Signal handler: TeamMember post_save for {instance.pk}, created={created}")
        
        if created and not hasattr(instance, 'teammemberprofile'):
            logger.info(f"Signal handler: Creating TeamMemberProfile for new TeamMember {instance.pk}")
            try:
                profile = TeamMemberProfile.objects.create(
                    team_member=instance,
                    level=1,
                    condition='NORMAL',
                    active_player=True if instance.role == TeamMember.Role.PLAYER else False,
                    is_official=instance.is_official if hasattr(instance, 'is_official') else False
                )
                logger.info(f"Signal handler: Successfully created TeamMemberProfile {profile.pk}")
            except Exception as e:
                logger.error(f"Signal handler: Error creating TeamMemberProfile: {str(e)}")
                logger.error(traceback.format_exc())
                raise
    except Exception as e:
        logger.error(f"Signal handler: Unexpected error: {str(e)}")
        logger.error(traceback.format_exc())
        raise
