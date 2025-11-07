from django.contrib import messages
from django.contrib.auth import login, authenticate, logout as auth_logout
from django.db import IntegrityError, transaction
from django.shortcuts import render, redirect
from django.utils.text import slugify

from .models import User
from .decorators import login_required, role_required
from .models import Student as StudentModel
from .models import TemporaryAccessRequest
from django.utils import timezone
from django.db import models
from .models import Violation, LoginActivity


############################################
# Authentication
# - GET /login/ renders the login page
# - POST /login/student/ authenticates Student by Student ID
############################################

def login_view(request):
	"""Render the login page; redirects authenticated users to their dashboard."""
	# Redirect authenticated users to their dashboards
	if request.user.is_authenticated:
		return redirect("violations:route_dashboard")
	# Pull any prefill hints from session (set by failed student lookup, etc.)
	default_role = request.session.pop("login_prefill_role", None)
	prefill_student_id = request.session.pop("login_prefill_student_id", "")
	ctx = {
		"default_role": default_role,
		"prefill_student_id": prefill_student_id,
	}
	return render(request, "violations/login.html", ctx)


def student_login_auth(request):
	"""Authenticate a student by Student ID and log them in.

	If not found, re-render login with a suggestion to sign up.
	"""
	if request.method != "POST":
		return redirect("violations:login")

	student_id = (request.POST.get("student_id") or "").strip()
	if not student_id:
		messages.error(request, "Please enter your Student ID number.")
		return render(request, "violations/login.html", status=400)

	try:
		student = StudentModel.objects.select_related("user").get(student_id=student_id)
	except StudentModel.DoesNotExist:
		messages.warning(
			request,
			"We couldn't find that Student ID. You can sign up to create your account."
		)
		# Suggest the UI to keep Student role active
		request.session["login_prefill_role"] = "student"
		request.session["login_prefill_student_id"] = student_id
		return render(request, "violations/login.html", status=404)

	user = student.user
	if not user.is_active:
		messages.error(request, "Your account is inactive. Please contact support.")
		return render(request, "violations/login.html", status=403)

	# Log in the user via default backend (no password flow for Student ID auth)
	login(request, user, backend="django.contrib.auth.backends.ModelBackend")
	return redirect("violations:route_dashboard")


def credentials_login_auth(request):
	"""Authenticate Staff/Faculty using email + password.

	Students should use Student ID login instead; if a Student attempts this route,
	show a helpful message.
	"""
	if request.method != "POST":
		return redirect("violations:login")

	# Accept multiple possible field names from the UI
	identifier = (
		(request.POST.get("username") or
		 request.POST.get("faculty_username") or
		 request.POST.get("email") or
		 request.POST.get("staff_email") or
		 request.POST.get("faculty_email") or
		 "").strip()
	)
	password = (
		(request.POST.get("password") or
		 request.POST.get("staff_password") or
		 request.POST.get("faculty_password") or
		 "")
	)

	if not identifier or not password:
		messages.error(request, "Please provide both email and password.")
		return render(request, "violations/login.html", status=400)

	# Try authentication in a robust way:
	# 1) Treat identifier as username directly
	user = authenticate(request, username=identifier, password=password)
	# 2) If that fails and identifier looks like an email, resolve to username by email
	if user is None and "@" in identifier:
		from .models import User as UserModel
		try:
			match = UserModel.objects.get(email__iexact=identifier)
			user = authenticate(request, username=match.username, password=password)
		except UserModel.DoesNotExist:
			user = None
	if user is None:
		messages.error(request, "Invalid email or password.")
		return render(request, "violations/login.html", status=401)

	if not user.is_active:
		messages.error(request, "Your account is inactive. Please contact support.")
		return render(request, "violations/login.html", status=403)

	# Enforce role: this endpoint is intended for Staff/Faculty (and superusers)
	role = getattr(user, "role", None)
	if not getattr(user, "is_superuser", False) and role == getattr(User.Role, "STUDENT", "student"):
		messages.warning(request, "Students, please sign in using your Student ID number.")
		# Keep the student role active in UI
		request.session["login_prefill_role"] = "student"
		return render(request, "violations/login.html", status=400)

	# If user selected the Faculty role in the UI, require Django superuser
	selected_role = (request.POST.get("role") or "").strip().lower()
	if selected_role == "faculty" and not getattr(user, "is_superuser", False):
		messages.error(request, "Only Django admin superusers can sign in as Faculty.")
		request.session["login_prefill_role"] = "faculty"
		return render(request, "violations/login.html", status=403)

	login(request, user, backend="django.contrib.auth.backends.ModelBackend")
	return redirect("violations:route_dashboard")


def logout_view(request):
	"""Log out the current user and redirect to login (allows GET for convenience)."""
	auth_logout(request)
	return redirect("violations:login")


def signup_view(request):
	"""Signup page; handles Student signup on POST, renders UI on GET."""
	if request.method == "POST":
		role = request.POST.get("role", "student")

		if role != getattr(User.Role, "STUDENT", "student"):
			messages.error(request, "Only Student signup is available right now.")
			return render(request, "violations/signup.html", status=400)

		# Collect basic fields
		student_id = (request.POST.get("student_id") or "").strip()
		name = (request.POST.get("student_name") or "").strip()
		email = (request.POST.get("student_email") or "").strip().lower()
		password = request.POST.get("student_password") or ""

		# Student profile fields
		program = (request.POST.get("student_program") or "").strip()
		year_level_raw = (request.POST.get("student_year_level") or "").strip()
		department = (request.POST.get("student_department") or "").strip()
		enrollment_status = (request.POST.get("student_enrollment_status") or "Active").strip()
		contact_number = (request.POST.get("student_contact_number") or "").strip()
		guardian_name = (request.POST.get("guardian_name") or "").strip()
		guardian_contact = (request.POST.get("guardian_contact") or "").strip()
		profile_image = request.FILES.get("student_profile_image")

		# Basic validation
		missing = [
			k for k, v in {
				"Student ID": student_id,
				"Name": name,
				"Email": email,
				"Password": password,
				"Program": program,
				"Year Level": year_level_raw,
				"Department": department,
				"Enrollment Status": enrollment_status,
				"Contact Number": contact_number,
				"Guardian Name": guardian_name,
				"Guardian Contact": guardian_contact,
			}.items() if not v
		]
		if missing:
			messages.error(request, f"Please fill in all required fields: {', '.join(missing)}.")
			return render(request, "violations/signup.html", status=400)

		try:
			year_level = int(year_level_raw)
		except ValueError:
			messages.error(request, "Year Level must be a number.")
			return render(request, "violations/signup.html", status=400)

		# Create user and update student profile
		try:
			with transaction.atomic():
				# Use email as username to keep uniqueness simple
				username = email or slugify(name) or student_id
				user = User.objects.create_user(
					username=username,
					email=email,
					password=password,
					role=User.Role.STUDENT,
				)
				# Optional: store name into first_name for display
				if name:
					user.first_name = name
					user.save(update_fields=["first_name"])

				# Signals created a Student profile; update it
				student = getattr(user, "student_profile", None)
				if student is None:
					# Fallback if signal didn't fire for some reason
					from .models import Student as StudentModel

					student = StudentModel.objects.create(user=user, student_id=student_id)

				# Ensure unique student_id is set to provided value
				student.student_id = student_id
				student.program = program
				student.year_level = year_level
				student.department = department
				student.enrollment_status = enrollment_status
				student.contact_number = contact_number
				student.guardian_name = guardian_name
				student.guardian_contact = guardian_contact
				if profile_image:
					student.profile_image = profile_image
				student.save()

		except IntegrityError as e:
			# Likely duplicate email/username/student_id
			messages.error(request, "That email or student ID is already in use. Please try again.")
			return render(request, "violations/signup.html", status=400)

		# Auto-login and route to role dashboard
		login(request, user)
		return redirect("violations:route_dashboard")

	# GET: render UI
	return render(request, "violations/signup.html")


# Staff self-signup removed: staff accounts are created by administrators.


# Note: Faculty signup is not exposed—faculty are managed as superusers.


############################################
# Student (frontend-only)
############################################

@role_required({User.Role.STUDENT})
def student_dashboard_view(request):
	"""Student dashboard (UI-only) — restricted to Student role."""
	student = getattr(request.user, "student_profile", None)
	# Fetch real violations for this student
	violations = Violation.objects.select_related("reported_by", "student").filter(student=student).order_by("-created_at") if student else []
	# Login history for current user
	login_history = LoginActivity.objects.filter(user=request.user).order_by("-timestamp")[:20]
	ctx = {
		"student": student,
		"violations": violations,
		"login_history": login_history,
	}
	return render(request, "violations/student/dashboard.html", ctx)


############################################
# Faculty (Reporting Personnel) - frontend-only
############################################

@role_required({User.Role.FACULTY_ADMIN})
def faculty_dashboard_view(request):
	"""Faculty dashboard — shows quick stats for the current reporter."""
	# Aggregate counts for reports created by this user
	my_reports_qs = Violation.objects.filter(reported_by=request.user)
	total_reports = my_reports_qs.count()
	reported_count = my_reports_qs.filter(status=Violation.Status.REPORTED).count()
	under_review_count = my_reports_qs.filter(status=Violation.Status.UNDER_REVIEW).count()
	resolved_count = my_reports_qs.filter(status=Violation.Status.RESOLVED).count()
	pending_count = reported_count + under_review_count
	latest = my_reports_qs.order_by("-created_at").first()

	# include login history for modal
	login_history = LoginActivity.objects.filter(user=request.user).order_by("-timestamp")[:20]
	ctx = {
		"stats": {
			"total": total_reports,
			"pending": pending_count,
			"reported": reported_count,
			"under_review": under_review_count,
			"resolved": resolved_count,
			"latest_created_at": latest.created_at if latest else None,
		},
		"login_history": login_history,
	}
	return render(request, "violations/faculty/dashboard.html", ctx)


@role_required({User.Role.FACULTY_ADMIN})
def faculty_report_view(request):
	"""Faculty: Report Violation form — supports GET (form) and POST (create)."""
	if request.method == "POST":
		# Expect Student ID in student_search for MVP
		student_key = (request.POST.get("student_search") or "").strip()
		incident_dt = request.POST.get("incident_dt")
		vtype = request.POST.get("violation_type")
		location = (request.POST.get("location") or "").strip()
		description = (request.POST.get("description") or "").strip()
		witness = (request.POST.get("witness") or "").strip()
		evidence = request.FILES.get("evidence")

		missing = [k for k, v in {
			"Student": student_key,
			"Date/Time": incident_dt,
			"Type": vtype,
			"Location": location,
			"Description": description,
		}.items() if not v]
		if missing:
			messages.error(request, f"Please fill in all required fields: {', '.join(missing)}.")
			return render(request, "violations/faculty/report_form.html", status=400)

		# Resolve student by exact student_id first, else try name match (basic)
		try:
			student = StudentModel.objects.get(student_id__iexact=student_key)
		except StudentModel.DoesNotExist:
			# Fallback: try matching by user's first_name substring
			student = StudentModel.objects.select_related("user").filter(user__first_name__icontains=student_key).first()
			if not student:
				messages.error(request, "Student not found. Please provide a valid Student ID or name.")
				return render(request, "violations/faculty/report_form.html", status=404)

		# Parse datetime-local
		try:
			from datetime import datetime
			incident_at = datetime.fromisoformat(incident_dt)
		except Exception:
			messages.error(request, "Invalid date/time format.")
			return render(request, "violations/faculty/report_form.html", status=400)

		# Create violation
		v = Violation(
			student=student,
			reported_by=request.user,
			incident_at=incident_at,
			type=vtype,
			location=location,
			description=description,
			witness_statement=witness,
			status=Violation.Status.REPORTED,
		)
		if evidence:
			v.evidence_file = evidence
		v.save()
		messages.success(request, "Violation report submitted.")
		return redirect("violations:faculty_my_reports")

	return render(request, "violations/faculty/report_form.html")


@role_required({User.Role.FACULTY_ADMIN})
def faculty_my_reports_view(request):
	"""Faculty: My Reported Violations list — restricted to Faculty(Admin)."""
	my_reports = Violation.objects.select_related("student__user").filter(reported_by=request.user).order_by("-created_at")
	return render(request, "violations/faculty/my_reports.html", {"reports": my_reports})


############################################
# OSA Staff - frontend-only
############################################

@role_required({User.Role.STAFF})
def staff_dashboard_view(request):
	"""Staff dashboard — shows overview cards and a student directory table."""
	from .models import Student as StudentModel
	from django.db.models import Count, Sum, Case, When, IntegerField
	# Fetch students with related user for names; keep it simple (no pagination yet)
	students = (
		StudentModel.objects.select_related("user")
		.annotate(
			violations_count=Count("violations", distinct=True),
			pending_count=Sum(
				Case(
					When(violations__status__in=[Violation.Status.REPORTED, Violation.Status.UNDER_REVIEW], then=1),
					default=0,
					output_field=IntegerField(),
				)
			),
			resolved_count=Sum(
				Case(
					When(violations__status=Violation.Status.RESOLVED, then=1),
					default=0,
					output_field=IntegerField(),
				)
			),
			ongoing_count=Sum(
				Case(
					When(violations__status=Violation.Status.UNDER_REVIEW, then=1),
					default=0,
					output_field=IntegerField(),
				)
			),
		)
		.order_by("user__first_name", "user__last_name", "student_id")
	)
	# Violation-based metrics
	violation_qs = Violation.objects.all()
	# Total students (separate card)
	total_students = StudentModel.objects.count()
	# Distinct students that have at least one violation
	students_with_violations = StudentModel.objects.filter(violations__isnull=False).distinct().count()
	# Pending = newly reported + under review
	pending_violations = violation_qs.filter(status__in=[Violation.Status.REPORTED, Violation.Status.UNDER_REVIEW]).count()
	# Resolved
	resolved_violations = violation_qs.filter(status=Violation.Status.RESOLVED).count()
	# Ongoing sanctions (approximation: under_review status)
	ongoing_sanctions = violation_qs.filter(status=Violation.Status.UNDER_REVIEW).count()
	# include login history for modal
	login_history = LoginActivity.objects.filter(user=request.user).order_by("-timestamp")[:20]
	ctx = {
		"students": students,
		"total_students": total_students,
		"students_with_violations": students_with_violations,
		"pending_violations": pending_violations,
		"resolved_violations": resolved_violations,
		"ongoing_sanctions": ongoing_sanctions,
		"login_history": login_history,
	}
	return render(request, "violations/staff/dashboard.html", ctx)


@role_required({User.Role.STAFF})
def staff_student_detail_view(request, student_id: str):
	"""Staff: View a student's profile details and violations by student_id."""
	# Resolve student by ID (case-insensitive)
	student = StudentModel.objects.select_related("user").filter(student_id__iexact=student_id).first()
	if not student:
		messages.error(request, "Student not found.")
		return redirect("violations:staff_dashboard")

	# Fetch violations for this student
	vqs = Violation.objects.select_related("reported_by").filter(student=student).order_by("-created_at")
	total_v = vqs.count()
	pending_v = vqs.filter(status__in=[Violation.Status.REPORTED, Violation.Status.UNDER_REVIEW]).count()
	resolved_v = vqs.filter(status=Violation.Status.RESOLVED).count()
	dismissed_v = vqs.filter(status=Violation.Status.DISMISSED).count()
	latest_incident = vqs.first().incident_at if total_v else None
	ctx = {
		"student": student,
		"violations": vqs,
		"vstats": {
			"total": total_v,
			"pending": pending_v,
			"resolved": resolved_v,
			"dismissed": dismissed_v,
			"latest_incident": latest_incident,
		}
	}
	return render(request, "violations/staff/student_detail.html", ctx)


############################################
# Legacy helpers (optional)
############################################

def legacy_dashboard_redirect(request):
	"""Redirect old /dashboard/ to the Student dashboard for clarity."""
	return redirect("violations:student_dashboard")


@login_required
def route_dashboard_view(request):
	"""Role-aware router after login: sends users to their dashboard.

	If not authenticated, send to login.
	"""
	# Superusers act as Faculty(Admin) for routing purposes
	if getattr(request.user, "is_superuser", False):
		return redirect("violations:faculty_dashboard")

	role = getattr(request.user, "role", None)
	if role == getattr(getattr(type(request.user), "Role", object), "STUDENT", "student"):
		return redirect("violations:student_dashboard")
	if role == getattr(getattr(type(request.user), "Role", object), "FACULTY_ADMIN", "faculty_admin"):
		return redirect("violations:faculty_dashboard")
	if role == getattr(getattr(type(request.user), "Role", object), "STAFF", "staff"):
		# If staff has an active temporary access approval, route to faculty dashboard
		now = timezone.now()
		has_active = TemporaryAccessRequest.objects.filter(
			requester=request.user,
			status=TemporaryAccessRequest.Status.APPROVED,
		).filter(models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=now)).exists()
		if has_active:
			return redirect("violations:faculty_dashboard")
		return redirect("violations:staff_dashboard")

	# Fallback
	return redirect("violations:student_dashboard")
