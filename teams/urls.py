from django.conf import settings
from django.conf.urls.static import static
from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from .forms import EmailAuthenticationForm
from django.contrib.auth.views import LogoutView

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('login/', auth_views.LoginView.as_view(
        template_name='teams/login.html',
        authentication_form=EmailAuthenticationForm
    ), name='login'),
    path('logout/', views.CustomLogoutView.as_view(), name='logout'),
    path('register/', views.register, name='register'),
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
    path('profile/edit/', views.edit_profile, name='edit_profile'),
    path('profile/<int:user_id>/', views.view_profile, name='view_profile'),
    path('team/<int:team_id>/remove-invitation/<int:member_id>/', views.remove_pending_invitation, name='remove_pending_invitation'),
    path('team/<int:team_id>/seasons/', views.season_list, name='season_list'),
    path('team/<int:team_id>/seasons/create/', views.season_create, name='season_create'),
    path('team/<int:team_id>/seasons/<int:season_id>/', views.season_detail, name='season_detail'),
    path('team/<int:team_id>/seasons/<int:season_id>/edit/', views.season_edit, name='season_edit'),
    path('team/<int:team_id>/seasons/<int:season_id>/matches/create/', views.match_create, name='match_create'),
    path('team/<int:team_id>/seasons/<int:season_id>/matches/<int:match_id>/edit/', views.match_edit, name='match_edit'),
    path('teams/<int:team_id>/members/add/', views.add_team_member, name='add_team_member'),
    path('teams/<int:team_id>/members/<int:member_id>/remove/', views.remove_member, name='remove_member'),
    path('teams/<int:team_id>/members/<int:member_id>/toggle-admin/', views.toggle_team_admin, name='toggle_team_admin'),
    path('teams/<int:team_id>/members/<int:user_id>/edit/', views.edit_member, name='edit_member'),
    path('team/<int:team_id>/season/<int:season_id>/payments/', views.payment_list, name='payment_list'),
    path('team/<int:team_id>/season/<int:season_id>/payments/create/', views.payment_create, name='payment_create'),
    path('team/<int:team_id>/season/<int:season_id>/payments/<int:payment_id>/edit/', views.payment_edit, name='payment_edit'),
    path('team/<int:team_id>/season/<int:season_id>/payments/<int:payment_id>/delete/', views.payment_delete, name='payment_delete'),
    path('team/<int:team_id>/season/<int:season_id>/payments/<int:payment_id>/refresh/', views.refresh_players, name='refresh_players'),
    path('team/<int:team_id>/season/<int:season_id>/payments/<int:payment_id>/player/<int:player_payment_id>/', views.toggle_player_payment, name='toggle_player_payment'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)