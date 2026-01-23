from django.urls import path, include
from django.views.generic import RedirectView
from django.contrib.auth import views as auth_views
from . import views

# Optional namespace for clarity when reverse() is used from other apps
app_name = "violations"

# Role-specific URL includes
student_patterns = [
    path('login/', views.student_login_view, name='student_login'),
    path('login/auth/', views.student_login_auth, name='student_login_auth'),
    path('dashboard/', views.student_dashboard_view, name='student_dashboard'),
    path('apology/', views.student_apology_view, name='student_apology'),
    path('update-profile/', views.student_update_profile_view, name='student_update_profile'),
    path('message/<int:message_id>/read/', views.student_mark_message_read_view, name='student_mark_message_read'),
    path('message/reply/', views.student_reply_message_view, name='student_reply_message'),
    path('message/delete/', views.student_delete_message_view, name='student_delete_message'),
    path('message/restore/', views.student_restore_message_view, name='student_restore_message'),
]

staff_patterns = [
    path('login/', views.credentials_login_auth, name='staff_login'),
    path('dashboard/', views.staff_dashboard_view, name='staff_dashboard'),
    path('students/<str:student_id>/', views.staff_student_detail_view, name='staff_student_detail'),
    path('violations/', views.staff_violations_list_view, name='staff_violations_list'),
    path('violations/create/', views.staff_violation_create_view, name='staff_violation_create'),
    path('violations/check-student/', views.staff_check_student_view, name='staff_check_student'),
    path('violations/<int:violation_id>/', views.staff_violation_detail_view, name='staff_violation_detail'),
    path('violations/<int:violation_id>/edit/', views.staff_violation_edit_view, name='staff_violation_edit'),
    path('violations/<int:violation_id>/delete/', views.staff_violation_delete_view, name='staff_violation_delete'),
    path('violations/<int:violation_id>/verify/', views.staff_verify_violation_view, name='staff_verify_violation'),
    path('violations/documents/<int:document_id>/delete/', views.staff_delete_document_view, name='staff_delete_document'),
    path('apology-letters/', views.staff_apology_letters_view, name='staff_apology_letters'),
    path('apology-letters/<int:letter_id>/verify/', views.staff_verify_apology_view, name='staff_verify_apology'),
    path('apology-letters/<int:letter_id>/send-to-formator/', views.staff_send_to_formator_view, name='staff_send_to_formator'),
    path('reports/', views.staff_reports_view, name='staff_reports'),
    path('reports/export/', views.staff_export_report_view, name='staff_export_report'),
    path('reports/send/', views.staff_send_report_view, name='staff_send_report'),
    path('send-message/', views.staff_send_message_view, name='staff_send_message'),
    path('send-faculty-message/', views.staff_send_faculty_message_view, name='staff_send_faculty_message'),
    path('message/delete/', views.staff_delete_message_view, name='staff_delete_message'),
    path('message/restore/', views.staff_restore_message_view, name='staff_restore_message'),
    path('add-student/', views.staff_add_student_view, name='staff_add_student'),
    path('schedule-meeting/<int:alert_id>/', views.staff_schedule_meeting_view, name='staff_schedule_meeting'),
    path('resolve-alert/<int:alert_id>/', views.staff_resolve_alert_view, name='staff_resolve_alert'),
    path('mark-meeting-met/<int:alert_id>/', views.staff_mark_meeting_met_view, name='staff_mark_meeting_met'),
    path('dismiss-alert/<int:alert_id>/', views.staff_dismiss_alert_view, name='staff_dismiss_alert'),
    path('restore-alert/<int:alert_id>/', views.staff_restore_alert_view, name='staff_restore_alert'),
    path('delete-alert/<int:alert_id>/', views.staff_permanent_delete_alert_view, name='staff_delete_alert'),
]

faculty_patterns = [
    path('login/', views.faculty_login_view, name='faculty_login'),
    path('login/auth/', views.credentials_login_auth, name='faculty_login_auth'),
    path('dashboard/', views.faculty_dashboard_view, name='faculty_dashboard'),
    path('case-management/', views.faculty_case_management_view, name='faculty_case_management'),
    path('case-management/update-status/', views.faculty_update_case_status_view, name='faculty_update_case_status'),
    path('my-reports/', views.faculty_my_reports_view, name='faculty_my_reports'),
    path('activity-logs/', views.faculty_activity_logs_view, name='faculty_activity_logs'),
    path('activity-logs/<int:log_id>/delete/', views.faculty_delete_activity_log_view, name='faculty_delete_activity_log'),
    path('analytics/', views.faculty_analytics_view, name='faculty_analytics'),
    path('analytics/api/', views.faculty_analytics_api, name='faculty_analytics_api'),
    path('students/<str:student_id>/', views.faculty_student_detail_view, name='faculty_student_detail'),
    path('message/<int:message_id>/read/', views.faculty_mark_message_read_view, name='faculty_mark_message_read'),
    path('message/delete/', views.faculty_delete_message_view, name='faculty_delete_message'),
    path('message/restore/', views.faculty_restore_message_view, name='faculty_restore_message'),
    path('message/reply/', views.faculty_reply_message_view, name='faculty_reply_message'),
]

guard_patterns = [
    path('login/', views.guard_login_view, name='guard_login'),
    path('logout/', views.guard_logout_view, name='guard_logout'),
    path('dashboard/', views.guard_dashboard_view, name='guard_dashboard'),
    path('report-incident/', views.guard_report_incident_view, name='guard_report_incident'),
]

formator_patterns = [
    path('login/', views.formator_login_view, name='formator_login'),
    path('logout/', views.formator_logout_view, name='formator_logout'),
    path('dashboard/', views.formator_dashboard_view, name='formator_dashboard'),
    path('letter/<int:letter_id>/verify/', views.formator_verify_letter_view, name='formator_verify_letter'),
]

urlpatterns = [
    # General paths (e.g., home, APIs)
    path('', RedirectView.as_view(pattern_name='violations:login', permanent=False), name='home'),
    path('api/welcome-tts/', views.welcome_tts_view, name='welcome_tts'),
    path('api/detect-face/', views.detect_face_view, name='detect_face'),
    path('login/', views.login_view, name='login'),  # General login page (if needed)
    path('signup/', views.signup_view, name='signup'),
    path('dashboard/', views.legacy_dashboard_redirect, name='dashboard'),
    path('route/', views.route_dashboard_view, name='route_dashboard'),
    path('auth/login/', auth_views.LoginView.as_view(template_name='violations/auth/login.html'), name='auth_login'),
    path('auth/logout/', views.logout_view, name='auth_logout'),

    # Role-specific includes
    path('student/', include(student_patterns)),
    path('staff/', include(staff_patterns)),
    path('faculty/', include(faculty_patterns)),
    path('guard/', include(guard_patterns)),
    path('formator/', include(formator_patterns)),
]
