from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth import get_user_model
from .models import Team, TeamMember, Position, Profile, Season, Match

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
    profile_picture = forms.ImageField(required=False)

    class Meta:
        model = get_user_model()
        fields = ('email', 'first_name', 'last_name', 'date_of_birth', 'player_number', 'position', 'profile_picture', 'password1', 'password2')

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
            elif isinstance(field.widget, forms.FileInput):
                field.widget.attrs.update({'class': 'form-control'})
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
        user = super().save(commit=False)
        user.username = self.cleaned_data.get('email')  # Set username to email
        user.email = self.cleaned_data.get('email')  # Ensure email is set
        if commit:
            user.save()
            # Create or update profile
            profile = Profile.objects.get_or_create(user=user)[0]
            profile.player_number = self.cleaned_data['player_number']
            profile.position = self.cleaned_data['position']
            if self.cleaned_data.get('profile_picture'):
                profile.profile_picture = self.cleaned_data['profile_picture']
            profile.save()
        return user

class EmailAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(widget=forms.EmailInput(attrs={'autofocus': True}))

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

    def __init__(self, team, *args, **kwargs):
        self.team = team
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = self.cleaned_data['email']
        
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
    class Meta:
        model = Team
        fields = ('name', 'description')

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
    rut = forms.CharField(
        max_length=12,
        required=True,
        help_text="Chilean ID number (RUT)"
    )

    class Meta:
        model = get_user_model()
        fields = ('first_name', 'last_name', 'email', 'player_number', 'position', 'level', 'is_official', 'rut')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance:
            try:
                profile = self.instance.profile
                self.fields['player_number'].initial = profile.player_number
                self.fields['position'].initial = profile.position
                self.fields['level'].initial = profile.level
                self.fields['is_official'].initial = profile.is_official
                self.fields['rut'].initial = profile.rut
            except Profile.DoesNotExist:
                pass

        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'
        # Special handling for checkbox
        self.fields['is_official'].widget.attrs['class'] = 'form-check-input'

    def save(self, commit=True):
        user = super().save(commit=False)
        if commit:
            user.save()
            profile = Profile.objects.get_or_create(user=user)[0]
            profile.player_number = self.cleaned_data['player_number']
            profile.position = self.cleaned_data['position']
            profile.level = self.cleaned_data['level']
            profile.is_official = self.cleaned_data['is_official']
            profile.rut = self.cleaned_data['rut']
            profile.save()
        return user

class AdminMemberProfileForm(forms.ModelForm):
    first_name = forms.CharField(max_length=30, required=True)
    last_name = forms.CharField(max_length=30, required=True)
    email = forms.EmailField(required=True)
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
    rut = forms.CharField(
        max_length=12,
        required=True,
        help_text="Chilean ID number (RUT)"
    )

    class Meta:
        model = get_user_model()
        fields = ('first_name', 'last_name', 'email', 'player_number', 'position', 'level', 'is_official', 'rut')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance:
            try:
                profile = self.instance.profile
                self.fields['player_number'].initial = profile.player_number
                self.fields['position'].initial = profile.position
                self.fields['level'].initial = profile.level
                self.fields['is_official'].initial = profile.is_official
                self.fields['rut'].initial = profile.rut
            except Profile.DoesNotExist:
                pass

        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'
        # Special handling for checkbox
        self.fields['is_official'].widget.attrs['class'] = 'form-check-input'

    def save(self, commit=True):
        user = super().save(commit=False)
        if commit:
            user.save()
            profile = Profile.objects.get_or_create(user=user)[0]
            profile.player_number = self.cleaned_data['player_number']
            profile.position = self.cleaned_data['position']
            profile.level = self.cleaned_data['level']
            profile.is_official = self.cleaned_data['is_official']
            profile.rut = self.cleaned_data['rut']
            profile.save()
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

    class Meta:
        model = Season
        fields = ['name', 'start_date', 'end_date', 'is_active']
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

    class Meta:
        model = Match
        fields = ['opponent', 'match_date', 'match_time', 'field_number', 
                 'is_home_game', 'notes']
        widgets = {
            'opponent': forms.TextInput(attrs={'class': 'form-control'}),
            'is_home_game': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        self.season = kwargs.pop('season', None)
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        match_date = cleaned_data.get('match_date')
        
        if match_date and self.season:
            if match_date < self.season.start_date or match_date > self.season.end_date:
                raise forms.ValidationError(
                    "Match date must be within the season's date range "
                    f"({self.season.start_date} to {self.season.end_date})."
                )

        return cleaned_data 