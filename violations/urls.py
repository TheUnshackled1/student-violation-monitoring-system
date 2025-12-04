from django.urls import path
from django.views.generic import RedirectView
from django.contrib.auth import views as auth_views
from . import views
# Optional namespace for clarity when reverse() is used from other apps
app_name = "violations"

urlpatterns = [
    # Authentication
    # Home → redirect to the explicit login path (avoid duplicate URL names)
    path('', RedirectView.as_view(pattern_name='violations:login', permanent=False), name='home'),
    
    # Text-to-Speech API (Python-based welcome voice)
    path('api/welcome-tts/', views.welcome_tts_view, name='welcome_tts'),
    path('login/', views.login_view, name='login'),           # Explicit login path (renders login page)
    path('login/student/', views.student_login_auth, name='student_login'),  # Student login (by ID)
    path('login/credentials/', views.credentials_login_auth, name='credentials_login'),  # Staff/Faculty login (email+password)
    path('signup/', views.signup_view, name='signup'),        # Student Signup only
    # Faculty and Staff users are managed by admins; no self-signup routes.

    # Legacy convenience: old /dashboard/ → Student dashboard
    path('dashboard/', views.legacy_dashboard_redirect, name='dashboard'),

    # Role router after login
    path('route/', views.route_dashboard_view, name='route_dashboard'),

    # Student
    path('student/dashboard/', views.student_dashboard_view, name='student_dashboard'),
    path('student/message/<int:message_id>/read/', views.student_mark_message_read_view, name='student_mark_message_read'),
    path('student/message/reply/', views.student_reply_message_view, name='student_reply_message'),

    # Faculty (Reporting Personnel)
    path('faculty/dashboard/', views.faculty_dashboard_view, name='faculty_dashboard'),
    path('faculty/report/', views.faculty_report_view, name='faculty_report'),
    path('faculty/my-reports/', views.faculty_my_reports_view, name='faculty_my_reports'),
    path('faculty/students/<str:student_id>/', views.faculty_student_detail_view, name='faculty_student_detail'),

    # OSA Staff - Dashboard and Student Detail
    path('staff/dashboard/', views.staff_dashboard_view, name='staff_dashboard'),
    path('staff/students/<str:student_id>/', views.staff_student_detail_view, name='staff_student_detail'),
    
    # OSA Staff - Violation Management
    path('staff/violations/', views.staff_violations_list_view, name='staff_violations_list'),
    path('staff/violations/create/', views.staff_violation_create_view, name='staff_violation_create'),
    path('staff/violations/<int:violation_id>/', views.staff_violation_detail_view, name='staff_violation_detail'),
    path('staff/violations/<int:violation_id>/edit/', views.staff_violation_edit_view, name='staff_violation_edit'),
    path('staff/violations/<int:violation_id>/verify/', views.staff_verify_violation_view, name='staff_verify_violation'),
    path('staff/violations/documents/<int:document_id>/delete/', views.staff_delete_document_view, name='staff_delete_document'),
    
    # OSA Staff - Apology Letters
    path('staff/apology-letters/', views.staff_apology_letters_view, name='staff_apology_letters'),
    path('staff/apology-letters/<int:letter_id>/verify/', views.staff_verify_apology_view, name='staff_verify_apology'),
    
    # OSA Staff - ID Confiscation
    path('staff/id-confiscation/', views.staff_id_confiscation_view, name='staff_id_confiscation'),
    path('staff/id-confiscation/confiscate/', views.staff_confiscate_id_view, name='staff_confiscate_id'),
    path('staff/id-confiscation/<int:confiscation_id>/release/', views.staff_release_id_view, name='staff_release_id'),
    
    # OSA Staff - Clearances
    path('staff/clearances/', views.staff_clearances_view, name='staff_clearances'),
    path('staff/clearances/create/', views.staff_create_clearance_view, name='staff_create_clearance'),
    path('staff/clearances/<int:clearance_id>/update/', views.staff_update_clearance_view, name='staff_update_clearance'),
    
    # OSA Staff - Reports
    path('staff/reports/', views.staff_reports_view, name='staff_reports'),
    path('staff/reports/export/', views.staff_export_report_view, name='staff_export_report'),
    
    # OSA Staff - Messaging
    path('staff/send-message/', views.staff_send_message_view, name='staff_send_message'),
    
    # OSA Staff - Add Student
    path('staff/add-student/', views.staff_add_student_view, name='staff_add_student'),

    # Authentication (Django built-ins for testing/demo)
    path('auth/login/', auth_views.LoginView.as_view(template_name='violations/auth/login.html'), name='auth_login'),
    path('auth/logout/', views.logout_view, name='auth_logout'),
]
