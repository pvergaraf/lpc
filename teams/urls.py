from django.conf import settings
from django.conf.urls.static import static
from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from .forms import EmailAuthenticationForm, CustomPasswordResetForm
from django.contrib.auth.views import LogoutView
from .utils.logging_utils import log_error
import django

# Log URL patterns for debugging
log_error(
    None,
    error_message="URL patterns loading",
    error_type="URLConfiguration",
    extra_context={
        "app_name": "teams",
        "debug_mode": settings.DEBUG
    }
)

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('login/', auth_views.LoginView.as_view(
        template_name='teams/login.html',
        authentication_form=EmailAuthenticationForm
    ), name='login'),
    path('logout/', views.CustomLogoutView.as_view(), name='logout'),
    path('register/', views.register, name='register'),
    
    # Password Reset URLs
    path('password-reset/', auth_views.PasswordResetView.as_view(
        template_name='teams/password_reset.html',
        form_class=CustomPasswordResetForm,
        email_template_name='teams/email/password_reset_email.html',
        subject_template_name='teams/email/password_reset_subject.txt',
        success_url='/password-reset/done/'
    ), name='password_reset'),
    
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='teams/password_reset_done.html'
    ), name='password_reset_done'),
    
    path('password-reset-confirm/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='teams/password_reset_confirm.html',
        success_url='/password-reset-complete/'
    ), name='password_reset_confirm'),
    
    path('password-reset-complete/', auth_views.PasswordResetCompleteView.as_view(
        template_name='teams/password_reset_complete.html'
    ), name='password_reset_complete'),
    
    path('admin/teams/', views.admin_teams, name='admin_teams'),
    path('admin/teams/create/', views.create_team, name='create_team'),
    path('admin/teams/<int:team_id>/delete/', views.delete_team, name='delete_team'),
    path('team/<int:team_id>/members/', views.team_members, name='team_members'),
    path('team/<int:team_id>/invite/', views.invite_member, name='invite_member'),
    path('team/<int:team_id>/add-member/', views.add_team_member, name='add_team_member'),
    path('team/<int:team_id>/switch/', views.switch_team, name='switch_team'),
    path('team/<int:team_id>/edit/', views.edit_team, name='edit_team'),
    path('team/<int:team_id>/member/<int:member_id>/toggle-admin/', views.toggle_team_admin, name='toggle_team_admin'),
    path('team/<int:team_id>/member/<int:member_id>/remove/', views.remove_member, name='remove_member'),
    path('team/<int:team_id>/remove-invitation/<int:member_id>/', views.remove_pending_invitation, name='remove_pending_invitation'),
    path('team/<int:team_id>/seasons/', views.season_list, name='season_list'),
    path('team/<int:team_id>/seasons/create/', views.season_create, name='season_create'),
    path('team/<int:team_id>/seasons/<int:season_id>/', views.season_detail, name='season_detail'),
    path('team/<int:team_id>/seasons/<int:season_id>/edit/', views.season_edit, name='season_edit'),
    path('team/<int:team_id>/seasons/<int:season_id>/matches/create/', views.match_create, name='match_create'),
    path('team/<int:team_id>/seasons/<int:season_id>/matches/<int:match_id>/edit/', views.match_edit, name='match_edit'),
    path('team/<int:team_id>/seasons/<int:season_id>/matches/<int:match_id>/stats/', views.match_stats_edit, name='match_stats_edit'),
    path('teams/<int:team_id>/members/add/', views.add_team_member, name='add_team_member'),
    path('teams/<int:team_id>/members/<int:member_id>/remove/', views.remove_member, name='remove_member'),
    path('teams/<int:team_id>/members/<int:member_id>/toggle-admin/', views.toggle_team_admin, name='toggle_team_admin'),
    path('teams/<int:team_id>/members/<int:user_id>/edit/', views.edit_member, name='edit_member'),
    path('team/<int:team_id>/season/<int:season_id>/payments/', views.payment_list, name='payment_list'),
    path('team/<int:team_id>/season/<int:season_id>/payments/create/', views.payment_create, name='payment_create'),
    path('team/<int:team_id>/season/<int:season_id>/payments/<int:payment_id>/edit/', views.payment_edit, name='payment_edit'),
    path('team/<int:team_id>/season/<int:season_id>/payments/<int:payment_id>/delete/', views.payment_delete, name='payment_delete'),
    path('team/<int:team_id>/season/<int:season_id>/payments/<int:payment_id>/refresh/', views.refresh_players, name='refresh_players'),
    path('team/<int:team_id>/season/<int:season_id>/payments/<int:payment_id>/player/<int:player_payment_id>/toggle/', views.toggle_player_payment, name='toggle_player_payment'),
    path('update-condition/', views.update_condition, name='update_condition'),
    path('team/<int:team_id>/player/<int:user_id>/', views.player_card, name='player_card'),
    path('team/<int:team_id>/lineup/', views.lineup_simulator, name='lineup_simulator'),
    # Profile URLs
    path('profile/edit/', views.edit_profile, name='edit_profile'),
    path('profile/<int:user_id>/', views.view_profile, name='view_profile'),
]

# Log URL patterns after they're defined
log_error(
    None,
    error_message="URL patterns loaded",
    error_type="URLConfiguration",
    extra_context={
        "url_names": [pattern.name for pattern in urlpatterns if hasattr(pattern, 'name')]
    }
)

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)