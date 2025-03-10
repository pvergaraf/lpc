from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.utils.translation import gettext_lazy as _
from django.core.validators import MinValueValidator, MaxValueValidator
from PIL import Image
import os
from django.db.models.signals import post_save
from django.dispatch import receiver

class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('The Email field must be set')
        email = self.normalize_email(email)
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
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    profile_picture = models.ImageField(upload_to='profile_pics/', default='profile_pics/castolo.png', blank=True)
    player_number = models.IntegerField(null=True, blank=True)
    position = models.ForeignKey(Position, on_delete=models.SET_NULL, null=True, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    level = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(99)],
        default=1
    )
    is_official = models.BooleanField(default=False, help_text="Indicates if the player is officially registered")
    rut = models.CharField(max_length=12, blank=True, null=True, help_text="Chilean ID number (RUT)")

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.profile_picture and hasattr(self.profile_picture, 'path') and os.path.exists(self.profile_picture.path):
            img = Image.open(self.profile_picture.path)
            if img.height > 300 or img.width > 300:
                output_size = (300, 300)
                img.thumbnail(output_size)
                img.save(self.profile_picture.path)

    def __str__(self):
        return f"{self.user.get_full_name()}'s Profile"

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    if not hasattr(instance, 'profile'):
        Profile.objects.create(user=instance)
    instance.profile.save()

class Team(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

class Season(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='seasons')
    name = models.CharField(max_length=100)  # e.g., "Spring 2025"
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=True)
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
        from django.utils import timezone
        today = timezone.now().date()
        return self.start_date <= today <= self.end_date

class Match(models.Model):
    season = models.ForeignKey(Season, on_delete=models.CASCADE, related_name='matches')
    opponent = models.CharField(max_length=100)
    match_date = models.DateField()
    match_time = models.TimeField()
    field_number = models.PositiveIntegerField(help_text="Enter the field number")
    is_home_game = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['match_date', 'match_time']
        verbose_name_plural = 'matches'

    def __str__(self):
        home_team = self.season.team.name if self.is_home_game else self.opponent
        away_team = self.opponent if self.is_home_game else self.season.team.name
        return f"{home_team} vs {away_team} - {self.match_date}"

class TeamMember(models.Model):
    class Role(models.TextChoices):
        PLAYER = 'PLAYER', 'Player'
        MANAGER = 'MANAGER', 'Manager'
    
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    user = models.ForeignKey('teams.User', on_delete=models.CASCADE, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)  # For storing email before user registration
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.PLAYER)
    is_team_admin = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    invitation_token = models.CharField(max_length=64, null=True, blank=True, unique=True)
    invitation_accepted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [
            ('team', 'user'),  # A user can only be a member of a team once
            ('team', 'email'),  # An email can only be invited to a team once
        ]

    def __str__(self):
        if self.user:
            return f"{self.user.get_full_name()} - {self.team.name} ({self.get_role_display()})"
        return f"Pending Invitation ({self.email}) - {self.team.name}"
