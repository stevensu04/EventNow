from allauth.account.views import LoginView
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

# REST API (admin only)
router = DefaultRouter()
router.register(r'attendees', views.AttendeeViewSet)
router.register(r'notifications', views.NotificationViewSet)

urlpatterns = [
    # Public pages
    path('', views.landing_page, name='index'),
    path('about/', views.about_page, name='about'),
    path('pricing/', views.pricing_view, name='pricing'),
    path('pricing/switch/', views.switch_plan, name='switch_plan'),

    # Discovery & registration
    path('events/', views.registration0_page, name='event_list'),
    path('event/<int:event_id>/', views.event_detail_1_page, name='event_detail'),
    path('event/<int:event_id>/register/', views.register_event, name='register_event'),
    path('ticket/<str:token>/', views.ticket_page, name='ticket'),
    path('ticket/<str:token>/calendar.ics', views.ticket_ics, name='ticket_ics'),

    # Organiser
    path('login/', LoginView.as_view(template_name='login.html'), name='login'),
    path('dashboard/', views.dashboard_page, name='dashboard'),
    path('event/create/', views.create_event_page, name='create_event'),
    path('event/<int:event_id>/update/', views.update_event, name='update_event'),
    path('event/<int:event_id>/delete/', views.delete_event, name='delete_event'),
    path('event/<int:event_id>/sessions/', views.sessions_page, name='manage_sessions'),
    path('event/<int:event_id>/sessions/<int:session_id>/edit/', views.edit_session, name='edit_session'),
    path('event/<int:event_id>/sessions/<int:session_id>/delete/', views.delete_session, name='delete_session'),
    path('event/<int:event_id>/attendees/', views.manage_attendees, name='manage_attendees'),
    path('event/<int:event_id>/export/', views.export_attendees_csv, name='export_attendees_csv'),
    path('attendee/<int:attendee_id>/status/', views.update_attendee_status, name='update_attendee_status'),

    # AI features
    path('ai/describe/<int:event_id>/', views.generate_event_description, name='generate_ai_description'),
    path('ai/describe/', views.generate_ai_description_simple, name='generate_ai_description_simple'),
    path('ai/parse/', views.agentic_event_parser, name='agentic_parser'),

    # Integrations
    path('api/', include(router.urls)),
    path('accounts/', include('allauth.urls')),
]
