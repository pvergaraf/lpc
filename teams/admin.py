from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.translation import gettext_lazy as _
from .models import Team, TeamMember, User
from django.contrib import messages
import os
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ('email', 'first_name', 'last_name', 'is_staff', 'is_active')
    search_fields = ('email', 'first_name', 'last_name')
    ordering = ('email',)
    
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        (_('Personal info'), {'fields': ('first_name', 'last_name', 'date_of_birth')}),
        (_('Permissions'), {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        (_('Important dates'), {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'first_name', 'last_name', 'date_of_birth', 'password1', 'password2'),
        }),
    )

@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_at', 'updated_at')
    search_fields = ('name',)
    fields = ('name', 'description', 'team_photo')
    readonly_fields = ('created_at', 'updated_at')

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        form.base_fields['team_photo'].widget.attrs.update({
            'accept': 'image/*',  # Only accept image files
            'class': 'form-control'  # Add Bootstrap styling
        })
        return form

    def save_model(self, request, obj, form, change):
        if 'team_photo' in form.changed_data:
            file = request.FILES.get('team_photo')
            if file:
                # Validate file size (2MB limit)
                if file.size > 2 * 1024 * 1024:
                    messages.error(request, 'Team photo must be less than 2MB')
                    return

                # Validate file type
                allowed_extensions = ['.jpg', '.jpeg', '.png']
                file_extension = os.path.splitext(file.name)[1].lower()
                if file_extension not in allowed_extensions:
                    messages.error(request, 'Team photo must be JPEG or PNG')
                    return

                try:
                    # Save the file using default storage (S3)
                    file_name = f'team_photos/{obj.id}_{file.name}'
                    if default_storage.exists(file_name):
                        default_storage.delete(file_name)
                    
                    path = default_storage.save(file_name, ContentFile(file.read()))
                    obj.team_photo = path
                except Exception as e:
                    messages.error(request, f'Error saving team photo: {str(e)}')
                    return

        super().save_model(request, obj, form, change)

@admin.register(TeamMember)
class TeamMemberAdmin(admin.ModelAdmin):
    list_display = ('user', 'team', 'role', 'is_team_admin', 'is_active', 'invitation_accepted')
    list_filter = ('role', 'is_team_admin', 'is_active', 'invitation_accepted')
    search_fields = ('user__email', 'user__first_name', 'user__last_name', 'team__name')
    raw_id_fields = ('user', 'team')
