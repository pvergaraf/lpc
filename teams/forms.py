from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm, PasswordResetForm
from django.contrib.auth import get_user_model
from .models import Team, TeamMember, Position, Profile, Season, Match, Payment, PlayerPayment, TeamMemberProfile
from .utils.logging_utils import log_error
from .utils.team_utils import get_current_team

class UserRegistrationForm(UserCreationForm):
    first_name = forms.CharField(max_length=30, required=True)
    last_name = forms.CharField(max_length=30, required=True)
    date_of_birth = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date'}),
        required=True
    )
    email = forms.EmailField(required=True)
    player_number = forms.IntegerField(
        min_value=1,
        max_value=99,
        required=True,
        help_text="Choose a number between 1 and 99"
    )
    position = forms.ModelChoiceField(queryset=Position.objects.all(), required=True,
                                    help_text="Select your primary playing position")
    level = forms.IntegerField(
        min_value=1,
        max_value=99,
        required=True,
        initial=1,
        help_text="Player level (1-99)"
    )
    rut = forms.CharField(
        max_length=12,
        required=True,
        help_text="Chilean ID number (RUT)"
    )
    country = forms.ChoiceField(
        choices=Profile.COUNTRIES,
        required=True,
        initial='CL',
        help_text="Select your country"
    )
    description = forms.CharField(
        max_length=20,
        required=True,
        help_text="A short description (max 20 characters)"
    )

    class Meta:
        model = get_user_model()
        fields = ('email', 'first_name', 'last_name', 'date_of_birth', 'player_number', 'position', 'level', 'rut', 'country', 'description', 'password1', 'password2')

    def __init__(self, *args, **kwargs):
        self.invited_email = kwargs.pop('email', None)
        super().__init__(*args, **kwargs)
        if self.invited_email:
            self.fields['email'].initial = self.invited_email
            self.fields['email'].widget.attrs['readonly'] = True
            # Remove unique validator for email field
            self.fields['email'].validators = []
        
        # Add Bootstrap classes
        for field in self.fields.values():
            if isinstance(field.widget, forms.DateInput):
                field.widget.attrs.update({'class': 'form-control', 'type': 'date'})
            else:
                field.widget.attrs.update({'class': 'form-control'})

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if self.invited_email:
            return self.invited_email
        return email

    def clean(self):
        cleaned_data = super().clean()
        # If this is an invited registration, bypass the unique email validation
        if self.invited_email:
            # Remove any email-related errors
            if 'email' in self._errors:
                del self._errors['email']
            cleaned_data['email'] = self.invited_email
        return cleaned_data

    def save(self, commit=True):
        try:
            user = super().save(commit=False)
            user.username = self.cleaned_data.get('email')  # Set username to email
            user.email = self.cleaned_data.get('email')  # Ensure email is set
            user.date_of_birth = self.cleaned_data.get('date_of_birth')  # Set date of birth
            
            log_error(
                None,  # No request object in form
                error_message="Form save debug info",
                error_type="RegistrationDebug",
                extra_context={
                    "form_data": self.cleaned_data,
                    "commit": commit,
                    "user_data": {
                        "username": user.username,
                        "email": user.email,
                        "date_of_birth": user.date_of_birth,
                        "first_name": user.first_name,
                        "last_name": user.last_name
                    }
                }
            )
            
            if commit:
                user.save()
            return user
            
        except Exception as e:
            log_error(
                None,  # No request object in form
                error_message=f"Form save error: {str(e)}",
                error_type="RegistrationError",
                extra_context={
                    "form_data": self.cleaned_data,
                    "error": str(e)
                }
            )
            raise

class EmailAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your email',
            'autofocus': True
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Password'
        })
    )
    remember_me = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        })
    )

    def clean_username(self):
        return self.cleaned_data['username'].lower()

class TeamMemberInviteForm(forms.Form):
    email = forms.EmailField(required=True, widget=forms.EmailInput(attrs={'class': 'form-control'}))
    role = forms.ChoiceField(
        choices=TeamMember.Role.choices,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    is_team_admin = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        help_text="Give this member admin privileges for the team"
    )
    is_official = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        help_text="Mark this player as officially registered"
    )
    active_player = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        help_text="Mark if the player is currently active"
    )

    def __init__(self, team, *args, **kwargs):
        self.team = team
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = self.cleaned_data['email'].lower()
        
        # Check for active members with this email
        active_member = TeamMember.objects.filter(
            team=self.team,
            is_active=True,
            user__email=email
        ).exists()
        
        if active_member:
            raise forms.ValidationError("This user is already an active member of the team.")
        
        # Check for pending invitations (not accepted, not inactive)
        pending_invite = TeamMember.objects.filter(
            team=self.team,
            is_active=False,
            invitation_accepted=False,
            invitation_token__isnull=False,  # Only check for actual pending invites
            email=email
        ).exists()
        
        if pending_invite:
            raise forms.ValidationError("An invitation has already been sent to this email.")
        
        return email

class TeamForm(forms.ModelForm):
    team_photo = forms.ImageField(
        required=False,
        help_text="Upload a square team photo (will be cropped if not square)",
        widget=forms.FileInput(attrs={'class': 'form-control'})
    )

    class Meta:
        model = Team
        fields = ('name', 'description', 'team_photo')
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

class AddTeamMemberForm(UserCreationForm):
    first_name = forms.CharField(max_length=30, required=True)
    last_name = forms.CharField(max_length=30, required=True)
    email = forms.EmailField(required=True)
    date_of_birth = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date'}),
        required=True
    )
    role = forms.ChoiceField(choices=TeamMember.Role.choices)
    is_team_admin = forms.BooleanField(required=False, initial=False,
                                     help_text="Give this member admin privileges for the team")

    class Meta:
        model = get_user_model()
        fields = ('email', 'first_name', 'last_name', 'date_of_birth',
                 'password1', 'password2', 'role', 'is_team_admin')

class UserProfileForm(forms.ModelForm):
    first_name = forms.CharField(max_length=30, required=True)
    last_name = forms.CharField(max_length=30, required=True)
    email = forms.EmailField(required=True)
    date_of_birth = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    rut = forms.CharField(max_length=12, required=False)
    country = forms.ChoiceField(choices=Profile.COUNTRIES, required=False)
    player_number = forms.IntegerField(required=False, min_value=0, max_value=99)
    position = forms.ModelChoiceField(queryset=Position.objects.all(), required=False)
    level = forms.IntegerField(
        min_value=1,
        max_value=99,
        required=False,
        help_text="Player level (1-99)"
    )
    description = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}), required=False)
    profile_picture = forms.ImageField(required=False)

    class Meta:
        model = get_user_model()
        fields = ['first_name', 'last_name', 'email', 'date_of_birth', 'rut', 'country',
                 'player_number', 'position', 'level', 'description', 'profile_picture']

    def __init__(self, *args, team=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.team = team
        if self.instance:
            try:
                # Get shared profile data
                profile = self.instance.profile
                self.fields['rut'].initial = profile.rut
                self.fields['country'].initial = profile.country
                self.fields['date_of_birth'].initial = profile.date_of_birth
                
                # Get team-specific profile data
                if self.team:
                    team_member = self.instance.teammember_set.get(team=self.team)
                    team_profile = team_member.teammemberprofile
                    self.fields['player_number'].initial = team_profile.player_number
                    self.fields['position'].initial = team_profile.position
                    self.fields['level'].initial = team_profile.level
                    self.fields['description'].initial = team_profile.description
                    if team_profile.profile_picture:
                        self.fields['profile_picture'].initial = team_profile.profile_picture
            except (Profile.DoesNotExist, TeamMember.DoesNotExist, TeamMemberProfile.DoesNotExist):
                pass

        for field in self.fields.values():
            if isinstance(field.widget, forms.FileInput):
                field.widget.attrs['class'] = 'form-control'
            else:
                field.widget.attrs['class'] = 'form-control'

    def save(self, commit=True):
        user = super().save(commit=False)
        if commit:
            user.save()
            
            # Update shared profile data
            profile = Profile.objects.get_or_create(user=user)[0]
            profile.rut = self.cleaned_data['rut']
            profile.country = self.cleaned_data['country']
            profile.date_of_birth = self.cleaned_data['date_of_birth']
            profile.save()
            
            # Update team-specific profile data
            if self.team:
                team_member = TeamMember.objects.get(user=user, team=self.team)
                team_profile = TeamMemberProfile.objects.get_or_create(team_member=team_member)[0]
                team_profile.player_number = self.cleaned_data['player_number']
                team_profile.position = self.cleaned_data['position']
                team_profile.level = self.cleaned_data['level']
                team_profile.description = self.cleaned_data['description']
                if self.cleaned_data.get('profile_picture'):
                    team_profile.profile_picture = self.cleaned_data['profile_picture']
                team_profile.save()
        return user

class AdminMemberProfileForm(forms.ModelForm):
    first_name = forms.CharField(max_length=30, required=True)
    last_name = forms.CharField(max_length=30, required=True)
    email = forms.EmailField(required=True)
    
    # Shared profile fields
    rut = forms.CharField(
        max_length=12,
        required=True,
        help_text="Chilean ID number (RUT)"
    )
    country = forms.ChoiceField(
        choices=Profile.COUNTRIES,
        required=True,
        help_text="Select your country"
    )
    date_of_birth = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date'}),
        required=True,
        help_text="Player's date of birth"
    )
    
    # Team-specific fields
    player_number = forms.IntegerField(min_value=1, max_value=99, required=True)
    position = forms.ModelChoiceField(queryset=Position.objects.all(), required=True)
    level = forms.IntegerField(
        min_value=1, 
        max_value=99, 
        required=True,
        help_text="Player level (1-99)"
    )
    is_official = forms.BooleanField(
        required=False,
        help_text="Check if the player is officially registered"
    )
    active_player = forms.BooleanField(
        required=False,
        initial=True,
        help_text="Check if the player is currently active"
    )
    is_team_admin = forms.BooleanField(
        required=False,
        help_text="Give this member admin privileges for the team"
    )
    profile_picture = forms.ImageField(
        required=False,
        help_text="Upload a profile picture (optional)"
    )
    description = forms.CharField(
        max_length=20,
        required=False,
        help_text="A short description (max 20 characters)"
    )

    class Meta:
        model = get_user_model()
        fields = ('first_name', 'last_name', 'email', 'rut', 'country', 'date_of_birth',
                 'player_number', 'position', 'level', 'is_official', 'active_player',
                 'is_team_admin', 'profile_picture', 'description')

    def __init__(self, *args, team=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.team = team
        if self.instance:
            try:
                # Get shared profile data
                profile = self.instance.profile
                self.fields['rut'].initial = profile.rut
                self.fields['country'].initial = profile.country
                self.fields['date_of_birth'].initial = profile.date_of_birth
                
                # Get team-specific profile data
                team_member = self.instance.teammember_set.get(team=self.team)
                team_profile = team_member.teammemberprofile
                self.fields['player_number'].initial = team_profile.player_number
                self.fields['position'].initial = team_profile.position
                self.fields['level'].initial = team_profile.level
                self.fields['is_official'].initial = team_profile.is_official
                self.fields['active_player'].initial = team_profile.active_player
                self.fields['is_team_admin'].initial = team_member.is_team_admin
                self.fields['description'].initial = team_profile.description
                if team_profile.profile_picture:
                    self.fields['profile_picture'].initial = team_profile.profile_picture
            except (Profile.DoesNotExist, TeamMember.DoesNotExist, TeamMemberProfile.DoesNotExist):
                pass

        for field in self.fields.values():
            if isinstance(field.widget, forms.FileInput):
                field.widget.attrs['class'] = 'form-control'
            else:
                field.widget.attrs['class'] = 'form-control'
        # Special handling for checkboxes
        self.fields['is_official'].widget.attrs['class'] = 'form-check-input'
        self.fields['active_player'].widget.attrs['class'] = 'form-check-input'
        self.fields['is_team_admin'].widget.attrs['class'] = 'form-check-input'

    def save(self, commit=True):
        user = super().save(commit=False)
        if commit:
            user.save()
            
            # Update shared profile data
            profile = Profile.objects.get_or_create(user=user)[0]
            profile.rut = self.cleaned_data['rut']
            profile.country = self.cleaned_data['country']
            profile.date_of_birth = self.cleaned_data['date_of_birth']
            profile.save()
            
            # Update team-specific profile data
            team_member = TeamMember.objects.get(user=user, team=self.team)
            team_member.is_team_admin = self.cleaned_data['is_team_admin']
            team_member.save()
            
            team_profile = TeamMemberProfile.objects.get_or_create(team_member=team_member)[0]
            team_profile.player_number = self.cleaned_data['player_number']
            team_profile.position = self.cleaned_data['position']
            team_profile.level = self.cleaned_data['level']
            team_profile.is_official = self.cleaned_data['is_official']
            team_profile.active_player = self.cleaned_data['active_player']
            team_profile.description = self.cleaned_data['description']
            if self.cleaned_data.get('profile_picture'):
                team_profile.profile_picture = self.cleaned_data['profile_picture']
            team_profile.save()
        return user

class SeasonForm(forms.ModelForm):
    start_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        help_text="When does the season start?"
    )
    end_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        help_text="When does the season end?"
    )
    is_active = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        help_text="Make this the active season? Only one season can be active at a time."
    )
    slach_account = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g. lpcfc'
        }),
        help_text="Enter your Slach account name (e.g. lpcfc). This will be used in payment links: slach.cl/account/amount"
    )

    class Meta:
        model = Season
        fields = ['name', 'start_date', 'end_date', 'is_active', 'slach_account']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'})
        }

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')

        if start_date and end_date:
            if start_date > end_date:
                raise forms.ValidationError("End date must be after start date.")

            # Check for overlapping seasons
            team = self.instance.team if self.instance and self.instance.pk else None
            if team:
                overlapping = Season.objects.filter(
                    team=team,
                    start_date__lte=end_date,
                    end_date__gte=start_date
                )
                if self.instance.pk:
                    overlapping = overlapping.exclude(pk=self.instance.pk)
                if overlapping.exists():
                    raise forms.ValidationError(
                        "This season overlaps with another season. Please adjust the dates."
                    )

        return cleaned_data

class MatchForm(forms.ModelForm):
    match_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        help_text="When is the match?"
    )
    match_time = forms.TimeField(
        widget=forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
        help_text="What time is the match?"
    )
    field_number = forms.IntegerField(
        min_value=1,
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
        help_text="Enter the field number"
    )
    home_score = forms.IntegerField(
        min_value=0,
        required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
        help_text="Home team score"
    )
    away_score = forms.IntegerField(
        min_value=0,
        required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
        help_text="Away team score"
    )
    is_official = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        help_text="Check if this is an official match"
    )
    
    class Meta:
        model = Match
        fields = ['opponent', 'match_date', 'match_time', 'field_number', 
                 'is_home_game', 'home_score', 'away_score', 'notes', 'is_official']
        widgets = {
            'opponent': forms.TextInput(attrs={'class': 'form-control'}),
            'is_home_game': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        self.season = kwargs.pop('season', None)
        super().__init__(*args, **kwargs)

class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ['name', 'total_amount', 'due_date']
        widgets = {
            'due_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'total_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'})
        }

class PlayerPaymentForm(forms.ModelForm):
    class Meta:
        model = PlayerPayment
        fields = ['amount', 'admin_verified']
        labels = {
            'admin_verified': 'Payment Verified',
        }
        help_texts = {
            'admin_verified': 'Check this box to verify that the payment has been received and processed.'
        }

PlayerPaymentFormSet = forms.inlineformset_factory(
    Payment, PlayerPayment,
    form=PlayerPaymentForm,
    fields=['amount', 'admin_verified'],
    extra=0,
    can_delete=True
)

class CustomPasswordResetForm(PasswordResetForm):
    def clean_email(self):
        email = self.cleaned_data['email'].lower()
        return email 