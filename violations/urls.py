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
    
    # Face Detection API (for webcam head size detection)
    path('api/detect-face/', views.detect_face_view, name='detect_face'),
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
    path('student/apology/', views.student_apology_view, name='student_apology'),
    path('student/update-profile/', views.student_update_profile_view, name='student_update_profile'),
    path('student/message/<int:message_id>/read/', views.student_mark_message_read_view, name='student_mark_message_read'),
    path('student/message/reply/', views.student_reply_message_view, name='student_reply_message'),
    path('student/message/delete/', views.student_delete_message_view, name='student_delete_message'),
    path('student/message/restore/', views.student_restore_message_view, name='student_restore_message'),

    # OSA Coordinator (Reporting Personnel)
    path('faculty/dashboard/', views.faculty_dashboard_view, name='faculty_dashboard'),
    path('faculty/report/', views.faculty_report_view, name='faculty_report'),
    path('faculty/my-reports/', views.faculty_my_reports_view, name='faculty_my_reports'),
    path('faculty/students/<str:student_id>/', views.faculty_student_detail_view, name='faculty_student_detail'),
    path('faculty/message/<int:message_id>/read/', views.faculty_mark_message_read_view, name='faculty_mark_message_read'),
    path('faculty/message/delete/', views.faculty_delete_message_view, name='faculty_delete_message'),
    path('faculty/message/restore/', views.faculty_restore_message_view, name='faculty_restore_message'),
    path('faculty/message/reply/', views.faculty_reply_message_view, name='faculty_reply_message'),

    # OSA Staff - Dashboard and Student Detail
    path('staff/dashboard/', views.staff_dashboard_view, name='staff_dashboard'),
    path('staff/students/<str:student_id>/', views.staff_student_detail_view, name='staff_student_detail'),
    
    # OSA Staff - Violation Management
    path('staff/violations/', views.staff_violations_list_view, name='staff_violations_list'),
    path('staff/violations/create/', views.staff_violation_create_view, name='staff_violation_create'),
    path('staff/violations/check-student/', views.staff_check_student_view, name='staff_check_student'),
    path('staff/violations/<int:violation_id>/', views.staff_violation_detail_view, name='staff_violation_detail'),
    path('staff/violations/<int:violation_id>/edit/', views.staff_violation_edit_view, name='staff_violation_edit'),
    path('staff/violations/<int:violation_id>/delete/', views.staff_violation_delete_view, name='staff_violation_delete'),
    path('staff/violations/<int:violation_id>/verify/', views.staff_verify_violation_view, name='staff_verify_violation'),
    path('staff/violations/documents/<int:document_id>/delete/', views.staff_delete_document_view, name='staff_delete_document'),
    
    # OSA Staff - Apology Letters
    path('staff/apology-letters/', views.staff_apology_letters_view, name='staff_apology_letters'),
    path('staff/apology-letters/<int:letter_id>/verify/', views.staff_verify_apology_view, name='staff_verify_apology'),
    path('staff/apology-letters/<int:letter_id>/send-to-formator/', views.staff_send_to_formator_view, name='staff_send_to_formator'),
    
    # OSA Staff - Reports
    path('staff/reports/', views.staff_reports_view, name='staff_reports'),
    path('staff/reports/export/', views.staff_export_report_view, name='staff_export_report'),
    
    # OSA Staff - Messaging
    path('staff/send-message/', views.staff_send_message_view, name='staff_send_message'),
    path('staff/send-faculty-message/', views.staff_send_faculty_message_view, name='staff_send_faculty_message'),
    path('staff/message/delete/', views.staff_delete_message_view, name='staff_delete_message'),
    path('staff/message/restore/', views.staff_restore_message_view, name='staff_restore_message'),
    
    # OSA Staff - Add Student
    path('staff/add-student/', views.staff_add_student_view, name='staff_add_student'),
    
    # OSA Staff - Alert Management
    path('staff/schedule-meeting/<int:alert_id>/', views.staff_schedule_meeting_view, name='staff_schedule_meeting'),
    path('staff/resolve-alert/<int:alert_id>/', views.staff_resolve_alert_view, name='staff_resolve_alert'),

    # Guard Portal
    path('guard/login/', views.guard_login_view, name='guard_login'),
    path('guard/logout/', views.guard_logout_view, name='guard_logout'),
    path('guard/dashboard/', views.guard_dashboard_view, name='guard_dashboard'),
    path('guard/report-incident/', views.guard_report_incident_view, name='guard_report_incident'),

    # Student Formator Portal
    path('formator/login/', views.formator_login_view, name='formator_login'),
    path('formator/logout/', views.formator_logout_view, name='formator_logout'),
    path('formator/dashboard/', views.formator_dashboard_view, name='formator_dashboard'),
    path('formator/letter/<int:letter_id>/verify/', views.formator_verify_letter_view, name='formator_verify_letter'),

    # Authentication (Django built-ins for testing/demo)
    path('auth/login/', auth_views.LoginView.as_view(template_name='violations/auth/login.html'), name='auth_login'),
    path('auth/logout/', views.logout_view, name='auth_logout'),
]
