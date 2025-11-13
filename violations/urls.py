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

    # Faculty (Reporting Personnel)
    path('faculty/dashboard/', views.faculty_dashboard_view, name='faculty_dashboard'),
    path('faculty/report/', views.faculty_report_view, name='faculty_report'),
    path('faculty/my-reports/', views.faculty_my_reports_view, name='faculty_my_reports'),
    path('faculty/students/<str:student_id>/', views.faculty_student_detail_view, name='faculty_student_detail'),

    # OSA Staff
    path('staff/dashboard/', views.staff_dashboard_view, name='staff_dashboard'),
    path('staff/students/<str:student_id>/', views.staff_student_detail_view, name='staff_student_detail'),

    # Authentication (Django built-ins for testing/demo)
    path('auth/login/', auth_views.LoginView.as_view(template_name='violations/auth/login.html'), name='auth_login'),
    path('auth/logout/', views.logout_view, name='auth_logout'),
]
