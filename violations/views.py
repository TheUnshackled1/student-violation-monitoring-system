from django.contrib import messages
from django.contrib.auth import login, authenticate, logout as auth_logout
from django.db import IntegrityError, transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.text import slugify
from django.http import HttpResponse, JsonResponse
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Count, Sum, Case, When, IntegerField, Q
from django.utils import timezone
from django.db import models
from datetime import datetime
from io import BytesIO
import tempfile
import os
import csv

from .models import (
	User, Student as StudentModel, Staff as StaffModel, OSACoordinator as OSACoordinatorModel,
	TemporaryAccessRequest, Violation, LoginActivity,
	ViolationDocument, ApologyLetter, IDConfiscation, ViolationClearance, StaffVerification,
	Message
)
from .decorators import login_required, role_required


############################################
# Welcome TTS (server-side via Python library)
############################################

def welcome_tts_view(request):
	"""Generate welcome audio using a Python TTS library and return it as audio.

	Priority: gTTS -> pyttsx3. Returns MP3 if gTTS available, else WAV.
	Query params:
	  - text: optional explicit text to synthesize
	  - name: optional user name to include (used if text missing)
	  - role: optional role label (Student/Staff/Faculty) used for default text
	"""
	# Build text
	text = (request.GET.get("text") or "").strip()
	if not text:
		name = (request.GET.get("name") or getattr(request.user, "first_name", "") or getattr(request.user, "username", "") or "there").strip() or "there"
		role_raw = (request.GET.get("role") or getattr(getattr(request.user, "role", None), "lower", lambda: str(getattr(request.user, "role", "")))() or "").lower()
		if role_raw in {"osa_coordinator", "faculty_admin", "faculty"}:
			role_label = "OSA Coordinator"
		elif role_raw == "staff":
			role_label = "Staff"
		else:
			role_label = "Student"
		text = f"Welcome back, {name}. You are now on your {role_label} dashboard."

	# Try gTTS first (MP3)
	try:
		from gtts import gTTS  # type: ignore
		mp3_bytes = BytesIO()
		tts = gTTS(text=text, lang='en')
		tts.write_to_fp(mp3_bytes)
		mp3_bytes.seek(0)
		return HttpResponse(mp3_bytes.getvalue(), content_type='audio/mpeg')
	except ImportError:
		pass
	except Exception:
		# Fall through to next engine
		pass

	# Fallback: pyttsx3 (WAV via SAPI5 on Windows)
	try:
		import pyttsx3  # type: ignore
		fd, tmp_path = tempfile.mkstemp(suffix='.wav')
		os.close(fd)
		try:
			engine = pyttsx3.init()
			# Try pick a professional female voice
			target = None
			for v in engine.getProperty('voices'):
				n = (getattr(v, 'name', '') or '').lower()
				if any(k in n for k in ['female', 'zira', 'aria', 'samantha', 'victoria', 'karen', 'tessa', 'serena']):
					target = v.id
					break
			if target:
				engine.setProperty('voice', target)
			# Calm pace
			try:
				rate = engine.getProperty('rate')
				if isinstance(rate, int):
					engine.setProperty('rate', max(120, min(190, int(rate * 0.95))))
			except Exception:
				pass
			engine.setProperty('volume', 1.0)
			engine.save_to_file(text, tmp_path)
			engine.runAndWait()
			with open(tmp_path, 'rb') as f:
				data = f.read()
			return HttpResponse(data, content_type='audio/wav')
		finally:
			try:
				os.remove(tmp_path)
			except Exception:
				pass
	except ImportError:
		pass
	except Exception:
		pass

	return JsonResponse({
		"error": "No Python TTS engine available",
		"hint": "Install one of: gTTS (pip install gTTS) or pyttsx3 (pip install pyttsx3)."
	}, status=501)


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
	from django.db.models import Prefetch
	student = getattr(request.user, "student_profile", None)
	# Fetch real violations for this student with prefetched apology letters (latest first)
	violations = Violation.objects.select_related("reported_by", "student").prefetch_related(
		Prefetch("apology_letters", queryset=ApologyLetter.objects.order_by("-submitted_at"))
	).filter(student=student).order_by("-created_at") if student else []
	# Login history for current user
	login_history = LoginActivity.objects.filter(user=request.user).order_by("-timestamp")[:20]
	# Messages from staff/faculty - exclude deleted by receiver (student)
	messages_qs = Message.objects.select_related("sender").filter(
		receiver=request.user,
		deleted_by_receiver__isnull=True
	).order_by("-created_at")
	unread_count = messages_qs.filter(read_at__isnull=True).count()
	staff_messages = messages_qs[:20]
	# Trashed messages (deleted received messages)
	trashed_messages = Message.objects.select_related("sender", "receiver").filter(
		models.Q(sender=request.user, deleted_by_sender__isnull=False) |
		models.Q(receiver=request.user, deleted_by_receiver__isnull=False)
	).order_by("-created_at")[:30]
	ctx = {
		"student": student,
		"violations": violations,
		"login_history": login_history,
		"staff_messages": staff_messages,
		"unread_count": unread_count,
		"trashed_messages": trashed_messages,
	}
	return render(request, "violations/student/dashboard.html", ctx)


############################################
# OSA Coordinator (Reporting Personnel) - frontend-only
############################################

@role_required({User.Role.OSA_COORDINATOR})
def faculty_dashboard_view(request):
	"""OSA Coordinator dashboard — shows quick stats for the current reporter."""
	# Aggregate counts for reports created by this user
	my_reports_qs = Violation.objects.filter(reported_by=request.user)
	total_reports = my_reports_qs.count()
	reported_count = my_reports_qs.filter(status=Violation.Status.REPORTED).count()
	under_review_count = my_reports_qs.filter(status=Violation.Status.UNDER_REVIEW).count()
	resolved_count = my_reports_qs.filter(status=Violation.Status.RESOLVED).count()
	pending_count = reported_count + under_review_count
	latest = my_reports_qs.order_by("-created_at").first()

	# include login history for modal
	# Annotated student directory (violation counts per student)
	from django.db.models import Count, Sum, Case, When, IntegerField
	students_qs = (
		StudentModel.objects.select_related("user")
		.annotate(
			violations_count=Count("violations", distinct=True),
			minor_count=Sum(
				Case(
					When(violations__type=Violation.Severity.MINOR, then=1),
					default=0,
					output_field=IntegerField(),
				)
			),
			major_count=Sum(
				Case(
					When(violations__type=Violation.Severity.MAJOR, then=1),
					default=0,
					output_field=IntegerField(),
				)
			),
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
		)
		.order_by("user__first_name", "user__last_name", "student_id")
	)

	# Server-side pagination
	page = request.GET.get("page", 1)
	paginator = Paginator(students_qs, 25)  # 25 per page
	try:
		students_page = paginator.page(page)
	except PageNotAnInteger:
		students_page = paginator.page(1)
	except EmptyPage:
		students_page = paginator.page(paginator.num_pages)
	login_history = LoginActivity.objects.filter(user=request.user).order_by("-timestamp")[:20]
	# Messages from staff to this faculty - exclude deleted
	staff_messages_qs = Message.objects.select_related("sender").filter(
		receiver=request.user,
		deleted_by_receiver__isnull=True
	).order_by("-created_at")
	unread_count = staff_messages_qs.filter(read_at__isnull=True).count()
	staff_messages = staff_messages_qs[:20]
	# Trashed messages
	trashed_messages = Message.objects.select_related("sender", "receiver").filter(
		receiver=request.user,
		deleted_by_receiver__isnull=False
	).order_by("-created_at")[:30]
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
		"students": students_page,  # page object
		"paginator": paginator,
		"staff_messages": staff_messages,
		"unread_count": unread_count,
		"trashed_messages": trashed_messages,
	}
	return render(request, "violations/osa_coordinator/dashboard.html", ctx)


@role_required({User.Role.OSA_COORDINATOR})
def faculty_student_detail_view(request, student_id: str):
	"""OSA Coordinator: View a student's profile details and violations by student_id (mirrors staff detail)."""
	student = StudentModel.objects.select_related("user").filter(student_id__iexact=student_id).first()
	if not student:
		messages.error(request, "Student not found.")
		return redirect("violations:faculty_dashboard")
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


@role_required({User.Role.OSA_COORDINATOR})
def faculty_report_view(request):
	"""OSA Coordinator: Report Violation form — supports GET (form) and POST (create)."""
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
			return render(request, "violations/osa_coordinator/report_form.html", status=400)

		# Resolve student by exact student_id first, else try name match (basic)
		try:
			student = StudentModel.objects.get(student_id__iexact=student_key)
		except StudentModel.DoesNotExist:
			# Fallback: try matching by user's first_name substring
			student = StudentModel.objects.select_related("user").filter(user__first_name__icontains=student_key).first()
			if not student:
				messages.error(request, "Student not found. Please provide a valid Student ID or name.")
				return render(request, "violations/osa_coordinator/report_form.html", status=404)

		# Parse datetime-local
		try:
			from datetime import datetime
			incident_at = datetime.fromisoformat(incident_dt)
		except Exception:
			messages.error(request, "Invalid date/time format.")
			return render(request, "violations/osa_coordinator/report_form.html", status=400)

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

	return render(request, "violations/osa_coordinator/report_form.html")


@role_required({User.Role.OSA_COORDINATOR})
def faculty_my_reports_view(request):
	"""OSA Coordinator: My Reported Violations list — restricted to OSA Coordinator."""
	my_reports = Violation.objects.select_related("student__user").filter(reported_by=request.user).order_by("-created_at")
	return render(request, "violations/osa_coordinator/my_reports.html", {"reports": my_reports})


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
	# Sent messages to students (for tracking read status) - exclude deleted by sender
	sent_messages = Message.objects.select_related("receiver", "receiver__student_profile").filter(
		sender=request.user,
		deleted_by_sender__isnull=True
	).order_by("-created_at")[:30]
	# Student replies (messages FROM students TO this staff member) - exclude deleted by receiver
	student_replies = Message.objects.select_related("sender", "sender__student_profile").filter(
		receiver=request.user,
		deleted_by_receiver__isnull=True
	).order_by("-created_at")[:30]
	# Trashed messages (deleted sent messages OR deleted received messages)
	trashed_messages = Message.objects.select_related("sender", "receiver", "sender__student_profile", "receiver__student_profile").filter(
		models.Q(sender=request.user, deleted_by_sender__isnull=False) |
		models.Q(receiver=request.user, deleted_by_receiver__isnull=False)
	).order_by("-created_at")[:50]
	# OSA Coordinator list for messaging
	faculty_list = User.objects.filter(role=User.Role.OSA_COORDINATOR).order_by("first_name", "last_name")
	ctx = {
		"students": students,
		"total_students": total_students,
		"students_with_violations": students_with_violations,
		"pending_violations": pending_violations,
		"resolved_violations": resolved_violations,
		"ongoing_sanctions": ongoing_sanctions,
		"login_history": login_history,
		"sent_messages": sent_messages,
		"student_replies": student_replies,
		"trashed_messages": trashed_messages,
		"faculty_list": faculty_list,
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
	if role == getattr(getattr(type(request.user), "Role", object), "OSA_COORDINATOR", "osa_coordinator"):
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


############################################
# Staff Feature Views - Complete Implementation
############################################

@role_required({User.Role.STAFF})
def staff_violations_list_view(request):
	"""Staff: View all violations with filtering and search."""
	violations = Violation.objects.select_related('student', 'student__user', 'reported_by').order_by('-created_at')
	
	# Search
	search_query = request.GET.get('search', '')
	if search_query:
		violations = violations.filter(
			Q(student__student_id__icontains=search_query) |
			Q(student__user__first_name__icontains=search_query) |
			Q(student__user__last_name__icontains=search_query) |
			Q(description__icontains=search_query)
		)
	
	# Status filter
	status_filter = request.GET.get('status', '')
	if status_filter:
		violations = violations.filter(status=status_filter)
	
	# Type (severity) filter
	type_filter = request.GET.get('type', '')
	if type_filter:
		violations = violations.filter(type=type_filter)
	
	# Pagination
	paginator = Paginator(violations, 20)
	page = request.GET.get('page', 1)
	try:
		violations = paginator.page(page)
	except (PageNotAnInteger, EmptyPage):
		violations = paginator.page(1)
	
	ctx = {
		'violations': violations,
		'search_query': search_query,
		'status_filter': status_filter,
		'type_filter': type_filter,
		'status_choices': Violation.Status.choices,
		'type_choices': Violation.Severity.choices,
	}
	return render(request, 'violations/staff/violations_list.html', ctx)


@role_required({User.Role.STAFF})
def staff_violation_create_view(request):
	"""Staff: Create a new violation record from physical reports."""
	if request.method == 'POST':
		student_id = request.POST.get('student_id', '').strip()
		description = request.POST.get('description', '').strip()
		violation_type = request.POST.get('type', Violation.Severity.MINOR)
		location = request.POST.get('location', '').strip()
		incident_date = request.POST.get('incident_date', '')
		incident_time = request.POST.get('incident_time', '')
		
		# Validate student
		student = StudentModel.objects.filter(student_id__iexact=student_id).first()
		if not student:
			messages.error(request, f"Student with ID '{student_id}' not found.")
			return redirect('violations:staff_violation_create')
		
		# Parse incident datetime
		incident_at = timezone.now()
		if incident_date:
			try:
				if incident_time:
					incident_at = datetime.strptime(f"{incident_date} {incident_time}", "%Y-%m-%d %H:%M")
				else:
					incident_at = datetime.strptime(incident_date, "%Y-%m-%d")
				incident_at = timezone.make_aware(incident_at)
			except ValueError:
				pass
		
		# Create violation
		violation = Violation.objects.create(
			student=student,
			reported_by=request.user,
			description=description,
			type=violation_type,
			location=location or 'Not specified',
			incident_at=incident_at,
			status=Violation.Status.REPORTED,
		)
		
		# Handle document uploads
		documents = request.FILES.getlist('documents')
		for doc in documents:
			ViolationDocument.objects.create(
				violation=violation,
				document=doc,
				document_type='evidence',
				uploaded_by=request.user,
			)
		
		# Track offense frequency for this student
		offense_count = Violation.objects.filter(student=student).count()
		
		messages.success(request, f"Violation #{violation.id} created successfully. This is offense #{offense_count} for {student.user.get_full_name() or student.student_id}.")
		return redirect('violations:staff_violations_list')
	
	# GET request
	students = StudentModel.objects.select_related('user').all().order_by('student_id')
	ctx = {
		'students': students,
		'type_choices': Violation.Severity.choices,
	}
	return render(request, 'violations/staff/violation_form.html', ctx)


@role_required({User.Role.STAFF})
def staff_violation_edit_view(request, violation_id):
	"""Staff: Edit an existing violation record."""
	violation = get_object_or_404(Violation.objects.select_related('student', 'student__user'), id=violation_id)
	
	if request.method == 'POST':
		description = request.POST.get('description', '').strip()
		violation_type = request.POST.get('type', violation.type)
		status = request.POST.get('status', violation.status)
		location = request.POST.get('location', violation.location)
		incident_date = request.POST.get('incident_date', '')
		incident_time = request.POST.get('incident_time', '')
		
		violation.description = description
		violation.type = violation_type
		violation.location = location
		violation.status = status
		
		# Parse incident datetime
		if incident_date:
			try:
				if incident_time:
					incident_at = datetime.strptime(f"{incident_date} {incident_time}", "%Y-%m-%d %H:%M")
				else:
					incident_at = datetime.strptime(incident_date, "%Y-%m-%d")
				violation.incident_at = timezone.make_aware(incident_at)
			except ValueError:
				pass
		
		violation.save()
		
		# Handle new document uploads
		documents = request.FILES.getlist('documents')
		for doc in documents:
			ViolationDocument.objects.create(
				violation=violation,
				document=doc,
				document_type='evidence',
				uploaded_by=request.user,
			)
		
		messages.success(request, f"Violation #{violation.id} updated successfully.")
		return redirect('violations:staff_violations_list')
	
	# GET request
	existing_docs = ViolationDocument.objects.filter(violation=violation)
	ctx = {
		'violation': violation,
		'existing_docs': existing_docs,
		'type_choices': Violation.Severity.choices,
		'status_choices': Violation.Status.choices,
		'edit_mode': True,
	}
	return render(request, 'violations/staff/violation_form.html', ctx)


@role_required({User.Role.STAFF})
def staff_violation_delete_view(request, violation_id):
	"""Staff: Delete a violation record (with confirmation).
	
	This allows staff to remove a violation that was misapplied to a student.
	Related documents, apology letters, and other data will be cascade deleted.
	"""
	violation = get_object_or_404(
		Violation.objects.select_related('student', 'student__user', 'reported_by'),
		id=violation_id
	)
	
	if request.method == 'POST':
		student_name = violation.student.user.get_full_name() or violation.student.student_id
		violation_id_str = f"#{violation.id}"
		
		# Delete the violation (cascade deletes related documents, etc.)
		violation.delete()
		
		messages.success(request, f"Violation {violation_id_str} for {student_name} has been deleted successfully.")
		return redirect('violations:staff_violations_list')
	
	# GET request - show confirmation page
	ctx = {
		'violation': violation,
	}
	return render(request, 'violations/staff/violation_delete_confirm.html', ctx)


@role_required({User.Role.STAFF})
def staff_violation_detail_view(request, violation_id):
	"""Staff: View violation details with all related data."""
	violation = get_object_or_404(
		Violation.objects.select_related('student', 'student__user', 'reported_by'),
		id=violation_id
	)
	
	# Get related data
	documents = ViolationDocument.objects.filter(violation=violation)
	apology_letters = ApologyLetter.objects.filter(violation=violation)
	verifications = StaffVerification.objects.filter(violation=violation).select_related('verified_by')
	id_confiscation = IDConfiscation.objects.filter(violation=violation).first()
	
	# Get offense history for the student
	student_violations = Violation.objects.filter(student=violation.student).order_by('-created_at')
	offense_number = list(student_violations).index(violation) + 1 if violation in student_violations else 1
	total_offenses = student_violations.count()
	
	ctx = {
		'violation': violation,
		'documents': documents,
		'apology_letters': apology_letters,
		'verifications': verifications,
		'id_confiscation': id_confiscation,
		'offense_number': offense_number,
		'total_offenses': total_offenses,
		'student_violations': student_violations[:5],
	}
	return render(request, 'violations/staff/violation_detail.html', ctx)


@role_required({User.Role.STAFF})
def staff_verify_violation_view(request, violation_id):
	"""Staff: Verify/validate a violation record."""
	violation = get_object_or_404(Violation, id=violation_id)
	
	if request.method == 'POST':
		action = request.POST.get('action', 'verified')
		notes = request.POST.get('notes', '').strip()
		
		# Create verification record
		StaffVerification.objects.create(
			violation=violation,
			verified_by=request.user,
			action=action,
			notes=notes,
		)
		
		# Update violation status based on action
		if action == 'verified':
			if violation.status == Violation.Status.REPORTED:
				violation.status = Violation.Status.UNDER_REVIEW
				violation.save()
			messages.success(request, f"Violation #{violation.id} has been verified.")
		elif action == 'correction_needed':
			messages.warning(request, f"Violation #{violation.id} marked for correction.")
		elif action == 'escalated':
			messages.info(request, f"Violation #{violation.id} escalated to supervisor.")
		
		return redirect('violations:staff_violation_detail', violation_id=violation.id)
	
	return redirect('violations:staff_violation_detail', violation_id=violation.id)


@role_required({User.Role.STAFF})
def staff_apology_letters_view(request):
	"""Staff: View and manage apology letter submissions."""
	letters = ApologyLetter.objects.select_related(
		'violation', 'student', 'student__user', 'verified_by'
	).order_by('-submitted_at')
	
	# Filter by status
	status_filter = request.GET.get('status', '')
	if status_filter:
		letters = letters.filter(status=status_filter)
	
	# Search
	search_query = request.GET.get('search', '')
	if search_query:
		letters = letters.filter(
			Q(student__student_id__icontains=search_query) |
			Q(student__user__first_name__icontains=search_query) |
			Q(student__user__last_name__icontains=search_query)
		)
	
	# Pagination
	paginator = Paginator(letters, 20)
	page = request.GET.get('page', 1)
	try:
		letters = paginator.page(page)
	except (PageNotAnInteger, EmptyPage):
		letters = paginator.page(1)
	
	# Stats
	pending_count = ApologyLetter.objects.filter(status=ApologyLetter.Status.PENDING).count()
	approved_count = ApologyLetter.objects.filter(status=ApologyLetter.Status.APPROVED).count()
	rejected_count = ApologyLetter.objects.filter(status=ApologyLetter.Status.REJECTED).count()
	revision_count = ApologyLetter.objects.filter(status=ApologyLetter.Status.REVISION_NEEDED).count()
	
	ctx = {
		'letters': letters,
		'status_filter': status_filter,
		'search_query': search_query,
		'pending_count': pending_count,
		'approved_count': approved_count,
		'rejected_count': rejected_count,
		'revision_count': revision_count,
	}
	return render(request, 'violations/staff/apology_letters.html', ctx)


@role_required({User.Role.STAFF})
def staff_verify_apology_view(request, letter_id):
	"""Staff: Verify or reject an apology letter."""
	letter = get_object_or_404(ApologyLetter.objects.select_related('student', 'violation'), id=letter_id)
	
	if request.method == 'POST':
		action = request.POST.get('action', 'approved')
		remarks = request.POST.get('remarks', '').strip()
		
		letter.status = action
		letter.verified_by = request.user
		letter.verified_at = timezone.now()
		letter.remarks = remarks
		letter.save()
		
		if action == ApologyLetter.Status.APPROVED:
			messages.success(request, f"Apology letter from {letter.student.user.get_full_name() or letter.student.student_id} has been approved.")
		elif action == ApologyLetter.Status.REVISION_NEEDED:
			messages.warning(request, f"Apology letter from {letter.student.user.get_full_name() or letter.student.student_id} requires revision.")
		else:
			messages.error(request, f"Apology letter from {letter.student.user.get_full_name() or letter.student.student_id} has been rejected.")
		
		return redirect('violations:staff_apology_letters')
	
	ctx = {'letter': letter}
	return render(request, 'violations/staff/verify_apology.html', ctx)


@role_required({User.Role.STAFF})
def staff_id_confiscation_view(request):
	"""Staff: Manage student ID confiscation and releases."""
	confiscations = IDConfiscation.objects.select_related(
		'student', 'student__user', 'violation', 'confiscated_by', 'released_by'
	).order_by('-confiscated_at')
	
	# Filter by status
	status_filter = request.GET.get('status', '')
	if status_filter:
		confiscations = confiscations.filter(status=status_filter)
	
	# Search
	search_query = request.GET.get('search', '')
	if search_query:
		confiscations = confiscations.filter(
			Q(student__student_id__icontains=search_query) |
			Q(student__user__first_name__icontains=search_query) |
			Q(student__user__last_name__icontains=search_query)
		)
	
	# Pagination
	paginator = Paginator(confiscations, 20)
	page = request.GET.get('page', 1)
	try:
		confiscations = paginator.page(page)
	except (PageNotAnInteger, EmptyPage):
		confiscations = paginator.page(1)
	
	# Stats
	confiscated_count = IDConfiscation.objects.filter(status='confiscated').count()
	released_count = IDConfiscation.objects.filter(status='released').count()
	
	ctx = {
		'confiscations': confiscations,
		'status_filter': status_filter,
		'search_query': search_query,
		'confiscated_count': confiscated_count,
		'released_count': released_count,
	}
	return render(request, 'violations/staff/id_confiscation.html', ctx)


@role_required({User.Role.STAFF})
def staff_confiscate_id_view(request):
	"""Staff: Record a new ID confiscation."""
	if request.method == 'POST':
		student_id = request.POST.get('student_id', '').strip()
		violation_id = request.POST.get('violation_id', '')
		reason = request.POST.get('reason', '').strip()
		
		student = StudentModel.objects.filter(student_id__iexact=student_id).first()
		if not student:
			messages.error(request, f"Student with ID '{student_id}' not found.")
			return redirect('violations:staff_confiscate_id')
		
		# Check if already confiscated
		existing = IDConfiscation.objects.filter(student=student, status='confiscated').first()
		if existing:
			messages.warning(request, f"ID for {student.user.get_full_name() or student.student_id} is already confiscated.")
			return redirect('violations:staff_id_confiscation')
		
		violation = None
		if violation_id:
			violation = Violation.objects.filter(id=violation_id).first()
		
		IDConfiscation.objects.create(
			student=student,
			violation=violation,
			confiscated_by=request.user,
			reason=reason,
			status='confiscated',
		)
		
		messages.success(request, f"ID for {student.user.get_full_name() or student.student_id} has been confiscated.")
		return redirect('violations:staff_id_confiscation')
	
	# GET request
	students = StudentModel.objects.select_related('user').all().order_by('student_id')
	violations = Violation.objects.filter(status__in=[Violation.Status.REPORTED, Violation.Status.UNDER_REVIEW])
	ctx = {
		'students': students,
		'violations': violations,
	}
	return render(request, 'violations/staff/confiscate_id.html', ctx)


@role_required({User.Role.STAFF})
def staff_release_id_view(request, confiscation_id):
	"""Staff: Release a confiscated student ID."""
	confiscation = get_object_or_404(IDConfiscation, id=confiscation_id)
	
	if request.method == 'POST':
		release_notes = request.POST.get('release_notes', '').strip()
		
		confiscation.status = 'released'
		confiscation.released_by = request.user
		confiscation.released_at = timezone.now()
		confiscation.release_notes = release_notes
		confiscation.save()
		
		messages.success(request, f"ID for {confiscation.student.user.get_full_name() or confiscation.student.student_id} has been released.")
		return redirect('violations:staff_id_confiscation')
	
	ctx = {'confiscation': confiscation}
	return render(request, 'violations/staff/release_id.html', ctx)


@role_required({User.Role.STAFF})
def staff_clearances_view(request):
	"""Staff: View and manage student violation clearances."""
	clearances = ViolationClearance.objects.select_related(
		'student', 'student__user', 'cleared_by'
	).order_by('-created_at')
	
	# Filter by status
	status_filter = request.GET.get('status', '')
	if status_filter:
		clearances = clearances.filter(status=status_filter)
	
	# Search
	search_query = request.GET.get('search', '')
	if search_query:
		clearances = clearances.filter(
			Q(student__student_id__icontains=search_query) |
			Q(student__user__first_name__icontains=search_query) |
			Q(student__user__last_name__icontains=search_query)
		)
	
	# Pagination
	paginator = Paginator(clearances, 20)
	page = request.GET.get('page', 1)
	try:
		clearances = paginator.page(page)
	except (PageNotAnInteger, EmptyPage):
		clearances = paginator.page(1)
	
	# Stats
	pending_count = ViolationClearance.objects.filter(status='pending').count()
	cleared_count = ViolationClearance.objects.filter(status='cleared').count()
	withheld_count = ViolationClearance.objects.filter(status='withheld').count()
	
	ctx = {
		'clearances': clearances,
		'status_filter': status_filter,
		'search_query': search_query,
		'pending_count': pending_count,
		'cleared_count': cleared_count,
		'withheld_count': withheld_count,
	}
	return render(request, 'violations/staff/clearances.html', ctx)


@role_required({User.Role.STAFF})
def staff_create_clearance_view(request):
	"""Staff: Create a clearance request for a student."""
	if request.method == 'POST':
		student_id = request.POST.get('student_id', '').strip()
		academic_year = request.POST.get('academic_year', '').strip()
		semester = request.POST.get('semester', '').strip()
		notes = request.POST.get('notes', '').strip()
		
		student = StudentModel.objects.filter(student_id__iexact=student_id).first()
		if not student:
			messages.error(request, f"Student with ID '{student_id}' not found.")
			return redirect('violations:staff_create_clearance')
		
		# Check if clearance already exists for this period
		existing = ViolationClearance.objects.filter(
			student=student,
			academic_year=academic_year,
			semester=semester,
		).first()
		if existing:
			messages.warning(request, f"Clearance for {student.student_id} in {academic_year} {semester} already exists.")
			return redirect('violations:staff_clearances')
		
		# Check if student has unresolved violations
		unresolved = Violation.objects.filter(
			student=student,
			status__in=[Violation.Status.REPORTED, Violation.Status.UNDER_REVIEW]
		).count()
		
		requirements_met = unresolved == 0
		status = 'pending' if unresolved > 0 else 'cleared'
		
		clearance = ViolationClearance.objects.create(
			student=student,
			academic_year=academic_year,
			semester=semester,
			status=status,
			requirements_met=requirements_met,
			notes=notes,
		)
		
		if status == 'cleared':
			clearance.cleared_by = request.user
			clearance.cleared_at = timezone.now()
			clearance.save()
			messages.success(request, f"Clearance for {student.student_id} has been granted (no violations found).")
		else:
			messages.info(request, f"Clearance for {student.student_id} is pending ({unresolved} unresolved violations).")
		
		return redirect('violations:staff_clearances')
	
	# GET request
	students = StudentModel.objects.select_related('user').all().order_by('student_id')
	current_year = timezone.now().year
	academic_years = [f"{y}-{y+1}" for y in range(current_year-2, current_year+1)]
	semesters = ['First Semester', 'Second Semester', 'Summer']
	
	ctx = {
		'students': students,
		'academic_years': academic_years,
		'semesters': semesters,
	}
	return render(request, 'violations/staff/create_clearance.html', ctx)


@role_required({User.Role.STAFF})
def staff_update_clearance_view(request, clearance_id):
	"""Staff: Update clearance status."""
	clearance = get_object_or_404(ViolationClearance, id=clearance_id)
	
	if request.method == 'POST':
		status = request.POST.get('status', clearance.status)
		notes = request.POST.get('notes', '').strip()
		
		clearance.status = status
		clearance.notes = notes
		
		if status == 'cleared':
			clearance.cleared_by = request.user
			clearance.cleared_at = timezone.now()
			clearance.requirements_met = True
		
		clearance.save()
		
		messages.success(request, f"Clearance for {clearance.student.student_id} updated to {status}.")
		return redirect('violations:staff_clearances')
	
	ctx = {'clearance': clearance}
	return render(request, 'violations/staff/update_clearance.html', ctx)


@role_required({User.Role.STAFF})
def staff_reports_view(request):
	"""Staff: Generate and view violation reports."""
	# Date range filters
	start_date = request.GET.get('start_date', '')
	end_date = request.GET.get('end_date', '')
	report_type = request.GET.get('report_type', 'summary')
	
	violations = Violation.objects.select_related('student', 'student__user', 'reported_by')
	
	if start_date:
		try:
			start_dt = datetime.strptime(start_date, "%Y-%m-%d")
			violations = violations.filter(incident_at__gte=timezone.make_aware(start_dt))
		except ValueError:
			pass
	
	if end_date:
		try:
			end_dt = datetime.strptime(end_date, "%Y-%m-%d")
			violations = violations.filter(incident_at__lte=timezone.make_aware(end_dt))
		except ValueError:
			pass
	
	# Summary statistics
	total_violations = violations.count()
	by_type = violations.values('type').annotate(count=Count('id'))
	by_status = violations.values('status').annotate(count=Count('id'))
	
	# Top offenders
	top_offenders = (
		violations.values('student__student_id', 'student__user__first_name', 'student__user__last_name')
		.annotate(count=Count('id'))
		.order_by('-count')[:10]
	)
	
	# Monthly trend
	monthly_trend = (
		violations.extra(select={'month': "strftime('%%Y-%%m', incident_at)"})
		.values('month')
		.annotate(count=Count('id'))
		.order_by('month')
	)
	
	ctx = {
		'start_date': start_date,
		'end_date': end_date,
		'report_type': report_type,
		'total_violations': total_violations,
		'by_type': {item['type']: item['count'] for item in by_type},
		'by_status': {item['status']: item['count'] for item in by_status},
		'top_offenders': top_offenders,
		'monthly_trend': list(monthly_trend),
		'violations': violations.order_by('-incident_at')[:50],
	}
	return render(request, 'violations/staff/reports.html', ctx)


@role_required({User.Role.STAFF})
def staff_export_report_view(request):
	"""Staff: Export violation report as CSV."""
	start_date = request.GET.get('start_date', '')
	end_date = request.GET.get('end_date', '')
	
	violations = Violation.objects.select_related('student', 'student__user', 'reported_by').order_by('-incident_at')
	
	if start_date:
		try:
			start_dt = datetime.strptime(start_date, "%Y-%m-%d")
			violations = violations.filter(incident_at__gte=timezone.make_aware(start_dt))
		except ValueError:
			pass
	
	if end_date:
		try:
			end_dt = datetime.strptime(end_date, "%Y-%m-%d")
			violations = violations.filter(incident_at__lte=timezone.make_aware(end_dt))
		except ValueError:
			pass
	
	# Create CSV response
	response = HttpResponse(content_type='text/csv')
	response['Content-Disposition'] = f'attachment; filename="violations_report_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
	
	writer = csv.writer(response)
	writer.writerow(['ID', 'Student ID', 'Student Name', 'Description', 'Type', 'Status', 'Location', 'Incident Date', 'Reported By', 'Created At'])
	
	for v in violations:
		writer.writerow([
			v.id,
			v.student.student_id,
			v.student.user.get_full_name() or v.student.student_id,
			v.description,
			v.type,
			v.status,
			v.location,
			v.incident_at.strftime("%Y-%m-%d %H:%M") if v.incident_at else '',
			v.reported_by.get_full_name() if v.reported_by else '',
			v.created_at.strftime("%Y-%m-%d %H:%M"),
		])
	
	return response


@role_required({User.Role.STAFF})
def staff_delete_document_view(request, document_id):
	"""Staff: Delete a violation document."""
	document = get_object_or_404(ViolationDocument, id=document_id)
	violation_id = document.violation.id
	
	if request.method == 'POST':
		document.delete()
		messages.success(request, "Document deleted successfully.")
	
	return redirect('violations:staff_violation_detail', violation_id=violation_id)


@role_required({User.Role.STAFF})
def staff_send_message_view(request):
	"""Staff: Send a message to a student."""
	if request.method == 'POST':
		student_id = request.POST.get('student_id', '').strip()
		message_content = request.POST.get('message', '').strip()
		
		if not student_id or not message_content:
			messages.error(request, "Student ID and message are required.")
			return redirect('violations:staff_dashboard')
		
		# Find the student
		student = StudentModel.objects.select_related('user').filter(student_id__iexact=student_id).first()
		if not student:
			messages.error(request, f"Student with ID '{student_id}' not found.")
			return redirect('violations:staff_dashboard')
		
		# Create the message
		Message.objects.create(
			sender=request.user,
			receiver=student.user,
			content=message_content
		)
		
		messages.success(request, f"Message sent to {student.user.get_full_name() or student.student_id}.")
		return redirect('violations:staff_dashboard')
	
	return redirect('violations:staff_dashboard')


@role_required({User.Role.STAFF})
def staff_send_faculty_message_view(request):
	"""Staff: Send a message to a faculty member."""
	if request.method == 'POST':
		faculty_id = request.POST.get('faculty_id')
		message_content = request.POST.get('content', '').strip()
		
		if not faculty_id or not message_content:
			messages.error(request, 'Please select a faculty member and enter a message.')
			return redirect('violations:staff_dashboard')
		
		# Find the OSA Coordinator user
		faculty_user = User.objects.filter(id=faculty_id, role=User.Role.OSA_COORDINATOR).first()
		if not faculty_user:
			messages.error(request, 'OSA Coordinator not found.')
			return redirect('violations:staff_dashboard')
		
		# Create the message
		Message.objects.create(
			sender=request.user,
			receiver=faculty_user,
			content=message_content
		)
		
		messages.success(request, f'Message sent to {faculty_user.get_full_name() or faculty_user.username}.')
		return redirect('violations:staff_dashboard')
	
	messages.error(request, 'Invalid request method.')
	return redirect('violations:staff_dashboard')


@role_required({User.Role.STUDENT})
def student_mark_message_read_view(request, message_id):
	"""Student: Mark a message as read."""
	message_obj = get_object_or_404(Message, id=message_id, receiver=request.user)
	message_obj.mark_read()
	return JsonResponse({'status': 'ok'})


@role_required({User.Role.STUDENT})
def student_reply_message_view(request):
	"""Student: Reply to a staff message (limited to 10 characters)."""
	if request.method != 'POST':
		return JsonResponse({'status': 'error', 'error': 'POST required'}, status=405)
	
	try:
		import json
		data = json.loads(request.body)
		message_id = data.get('message_id')
		reply_text = data.get('reply', '').strip()
		
		if not message_id or not reply_text:
			return JsonResponse({'status': 'error', 'error': 'Missing message_id or reply'}, status=400)
		
		# Limit reply to 10 characters
		if len(reply_text) > 10:
			reply_text = reply_text[:10]
		
		# Get the original message to find the sender (staff)
		original_message = get_object_or_404(Message, id=message_id, receiver=request.user)
		
		# Create a reply message from student to staff
		Message.objects.create(
			sender=request.user,
			receiver=original_message.sender,
			content=reply_text
		)
		
		return JsonResponse({'status': 'ok'})
	except json.JSONDecodeError:
		return JsonResponse({'status': 'error', 'error': 'Invalid JSON'}, status=400)
	except Exception as e:
		return JsonResponse({'status': 'error', 'error': str(e)}, status=500)


@role_required({User.Role.STAFF})
def staff_add_student_view(request):
	"""Staff: Add a new student to the system."""
	if request.method == 'POST':
		# Get form data
		student_id = request.POST.get('student_id', '').strip()
		username = request.POST.get('username', '').strip()
		first_name = request.POST.get('first_name', '').strip()
		last_name = request.POST.get('last_name', '').strip()
		email = request.POST.get('email', '').strip()
		password = request.POST.get('password', '').strip()
		contact_number = request.POST.get('contact_number', '').strip()
		program = request.POST.get('program', '').strip()
		year_level = request.POST.get('year_level', '').strip()
		department = request.POST.get('department', '').strip()
		guardian_name = request.POST.get('guardian_name', '').strip()
		guardian_contact = request.POST.get('guardian_contact', '').strip()
		
		# Validate required fields
		if not all([student_id, username, first_name, last_name, password, program, year_level]):
			messages.error(request, "Please fill in all required fields.")
			return redirect('violations:staff_dashboard')
		
		# Check if student ID already exists
		if StudentModel.objects.filter(student_id__iexact=student_id).exists():
			messages.error(request, f"A student with ID '{student_id}' already exists.")
			return redirect('violations:staff_dashboard')
		
		# Check if username already exists
		if User.objects.filter(username__iexact=username).exists():
			messages.error(request, f"Username '{username}' is already taken.")
			return redirect('violations:staff_dashboard')
		
		# Check if email already exists (if provided)
		if email and User.objects.filter(email__iexact=email).exists():
			messages.error(request, f"Email '{email}' is already registered.")
			return redirect('violations:staff_dashboard')
		
		try:
			# Create the user account
			user = User.objects.create_user(
				username=username,
				email=email or None,
				password=password,
				first_name=first_name,
				last_name=last_name,
				role=User.Role.STUDENT
			)
			
			# Create the student profile
			StudentModel.objects.create(
				user=user,
				student_id=student_id,
				program=program,
				year_level=int(year_level),
				department=department or None,
				contact_number=contact_number or None,
				guardian_name=guardian_name or None,
				guardian_contact=guardian_contact or None,
				enrollment_status='Enrolled'
			)
			
			messages.success(request, f"Student '{first_name} {last_name}' ({student_id}) has been added successfully.")
		except Exception as e:
			messages.error(request, f"Error creating student: {str(e)}")
		
		return redirect('violations:staff_dashboard')
	
	return redirect('violations:staff_dashboard')


@role_required({User.Role.STAFF})
def staff_delete_message_view(request):
	"""Staff: Move a message to trash (soft delete)."""
	if request.method != 'POST':
		return JsonResponse({'status': 'error', 'error': 'POST required'}, status=405)
	
	try:
		import json
		data = json.loads(request.body)
		message_id = data.get('message_id')
		message_type = data.get('type', 'sent')  # 'sent' or 'received'
		
		if not message_id:
			return JsonResponse({'status': 'error', 'error': 'Missing message_id'}, status=400)
		
		if message_type == 'sent':
			msg = get_object_or_404(Message, id=message_id, sender=request.user)
		else:
			msg = get_object_or_404(Message, id=message_id, receiver=request.user)
		
		msg.delete_for_user(request.user)
		return JsonResponse({'status': 'ok'})
	except json.JSONDecodeError:
		return JsonResponse({'status': 'error', 'error': 'Invalid JSON'}, status=400)
	except Exception as e:
		return JsonResponse({'status': 'error', 'error': str(e)}, status=500)


@role_required({User.Role.STAFF})
def staff_restore_message_view(request):
	"""Staff: Restore a message from trash."""
	if request.method != 'POST':
		return JsonResponse({'status': 'error', 'error': 'POST required'}, status=405)
	
	try:
		import json
		data = json.loads(request.body)
		message_id = data.get('message_id')
		
		if not message_id:
			return JsonResponse({'status': 'error', 'error': 'Missing message_id'}, status=400)
		
		# Find message where user is sender or receiver
		msg = Message.objects.filter(id=message_id).filter(
			models.Q(sender=request.user) | models.Q(receiver=request.user)
		).first()
		
		if not msg:
			return JsonResponse({'status': 'error', 'error': 'Message not found'}, status=404)
		
		msg.restore_for_user(request.user)
		return JsonResponse({'status': 'ok'})
	except json.JSONDecodeError:
		return JsonResponse({'status': 'error', 'error': 'Invalid JSON'}, status=400)
	except Exception as e:
		return JsonResponse({'status': 'error', 'error': str(e)}, status=500)


@role_required({User.Role.STUDENT})
def student_delete_message_view(request):
	"""Student: Move a message to trash (soft delete)."""
	if request.method != 'POST':
		return JsonResponse({'status': 'error', 'error': 'POST required'}, status=405)
	
	try:
		import json
		data = json.loads(request.body)
		message_id = data.get('message_id')
		
		if not message_id:
			return JsonResponse({'status': 'error', 'error': 'Missing message_id'}, status=400)
		
		# Student can delete received messages (from staff) or sent messages (replies)
		msg = Message.objects.filter(id=message_id).filter(
			models.Q(sender=request.user) | models.Q(receiver=request.user)
		).first()
		
		if not msg:
			return JsonResponse({'status': 'error', 'error': 'Message not found'}, status=404)
		
		msg.delete_for_user(request.user)
		return JsonResponse({'status': 'ok'})
	except json.JSONDecodeError:
		return JsonResponse({'status': 'error', 'error': 'Invalid JSON'}, status=400)
	except Exception as e:
		return JsonResponse({'status': 'error', 'error': str(e)}, status=500)


@role_required({User.Role.STUDENT})
def student_restore_message_view(request):
	"""Student: Restore a message from trash."""
	if request.method != 'POST':
		return JsonResponse({'status': 'error', 'error': 'POST required'}, status=405)
	
	try:
		import json
		data = json.loads(request.body)
		message_id = data.get('message_id')
		
		if not message_id:
			return JsonResponse({'status': 'error', 'error': 'Missing message_id'}, status=400)
		
		msg = Message.objects.filter(id=message_id).filter(
			models.Q(sender=request.user) | models.Q(receiver=request.user)
		).first()
		
		if not msg:
			return JsonResponse({'status': 'error', 'error': 'Message not found'}, status=404)
		
		msg.restore_for_user(request.user)
		return JsonResponse({'status': 'ok'})
	except json.JSONDecodeError:
		return JsonResponse({'status': 'error', 'error': 'Invalid JSON'}, status=400)
	except Exception as e:
		return JsonResponse({'status': 'error', 'error': str(e)}, status=500)


@role_required({User.Role.OSA_COORDINATOR})
def faculty_mark_message_read_view(request, message_id: int):
	"""OSA Coordinator: Mark a message as read."""
	message_obj = get_object_or_404(Message, id=message_id, receiver=request.user)
	message_obj.mark_read()
	return JsonResponse({'status': 'ok'})


@role_required({User.Role.OSA_COORDINATOR})
def faculty_delete_message_view(request):
	"""OSA Coordinator: Move a message to trash (soft delete)."""
	if request.method != 'POST':
		return JsonResponse({'status': 'error', 'error': 'POST required'}, status=405)
	
	try:
		import json
		data = json.loads(request.body)
		message_id = data.get('message_id')
		
		if not message_id:
			return JsonResponse({'status': 'error', 'error': 'Missing message_id'}, status=400)
		
		msg = get_object_or_404(Message, id=message_id, receiver=request.user)
		msg.delete_for_user(request.user)
		return JsonResponse({'status': 'ok'})
	except json.JSONDecodeError:
		return JsonResponse({'status': 'error', 'error': 'Invalid JSON'}, status=400)
	except Exception as e:
		return JsonResponse({'status': 'error', 'error': str(e)}, status=500)


@role_required({User.Role.OSA_COORDINATOR})
def faculty_restore_message_view(request):
	"""OSA Coordinator: Restore a message from trash."""
	if request.method != 'POST':
		return JsonResponse({'status': 'error', 'error': 'POST required'}, status=405)
	
	try:
		import json
		data = json.loads(request.body)
		message_id = data.get('message_id')
		
		if not message_id:
			return JsonResponse({'status': 'error', 'error': 'Missing message_id'}, status=400)
		
		msg = get_object_or_404(Message, id=message_id, receiver=request.user)
		msg.restore_for_user(request.user)
		return JsonResponse({'status': 'ok'})
	except json.JSONDecodeError:
		return JsonResponse({'status': 'error', 'error': 'Invalid JSON'}, status=400)
	except Exception as e:
		return JsonResponse({'status': 'error', 'error': str(e)}, status=500)


@role_required({User.Role.OSA_COORDINATOR})
def faculty_reply_message_view(request):
	"""OSA Coordinator: Reply to a staff message."""
	if request.method != 'POST':
		return JsonResponse({'status': 'error', 'error': 'POST required'}, status=405)
	
	try:
		import json
		data = json.loads(request.body)
		message_id = data.get('message_id')
		reply_text = data.get('reply', '').strip()
		
		if not message_id or not reply_text:
			return JsonResponse({'status': 'error', 'error': 'Missing message_id or reply'}, status=400)
		
		# Get the original message to find the sender (staff)
		original_message = get_object_or_404(Message, id=message_id, receiver=request.user)
		
		# Create a reply message from faculty to staff
		Message.objects.create(
			sender=request.user,
			receiver=original_message.sender,
			content=reply_text
		)
		
		return JsonResponse({'status': 'ok', 'message': 'Reply sent successfully!'})
	except json.JSONDecodeError:
		return JsonResponse({'status': 'error', 'error': 'Invalid JSON'}, status=400)
	except Exception as e:
		return JsonResponse({'status': 'error', 'error': str(e)}, status=500)


############################################
# Student: Letter of Apology Submission
############################################

@role_required({User.Role.STUDENT})
def student_apology_view(request):
	"""Student view to submit letter of apology for violations."""
	student = getattr(request.user, "student_profile", None)
	if not student:
		messages.error(request, "Student profile not found.")
		return redirect("violations:student_dashboard")
	
	# Get all violations that need apology (not resolved, or those requiring apology)
	violations_needing_apology = Violation.objects.filter(
		student=student
	).exclude(
		status=Violation.Status.RESOLVED
	).order_by("-created_at")
	
	# Get existing apology letters for this student
	existing_apologies = ApologyLetter.objects.filter(student=student).select_related("violation")
	apology_by_violation = {a.violation_id: a for a in existing_apologies}
	
	if request.method == "POST":
		violation_id = request.POST.get("violation_id")
		apology_file = request.FILES.get("apology_file")  # Optional now
		
		# Get letter form data
		letter_date = request.POST.get("letter_date", "").strip()
		letter_campus = request.POST.get("letter_campus", "").strip()
		letter_full_name = request.POST.get("letter_full_name", "").strip()
		letter_home_address = request.POST.get("letter_home_address", "").strip()
		letter_program = request.POST.get("letter_program", "").strip()
		letter_violations = request.POST.get("letter_violations", "").strip()
		letter_printed_name = request.POST.get("letter_printed_name", "").strip()
		signature_data = request.POST.get("signature_data", "").strip()
		
		if not violation_id:
			messages.error(request, "Please select a violation.")
			return redirect("violations:student_apology")
		
		# Validate that at least form data is filled
		if not letter_full_name:
			messages.error(request, "Please fill out the letter form with your full name.")
			return redirect("violations:student_apology")
		
		# Validate file type if file is uploaded
		if apology_file:
			allowed_types = ['application/pdf', 'image/jpeg', 'image/png', 'image/jpg']
			if apology_file.content_type not in allowed_types:
				messages.error(request, "Please upload a PDF or image file (JPEG, PNG).")
				return redirect("violations:student_apology")
		
		# Get the violation
		violation = get_object_or_404(Violation, id=violation_id, student=student)
		
		# Check if already submitted and pending/approved
		existing = apology_by_violation.get(violation.id)
		if existing and existing.status in [ApologyLetter.Status.PENDING, ApologyLetter.Status.APPROVED]:
			messages.warning(request, f"You have already submitted an apology letter for this violation. Status: {existing.get_status_display()}")
			return redirect("violations:student_apology")
		
		# Create or update apology letter
		if existing and existing.status in [ApologyLetter.Status.REJECTED, ApologyLetter.Status.REVISION_NEEDED]:
			# Update existing rejected/revision needed letter
			if apology_file:
				existing.file = apology_file
			existing.status = ApologyLetter.Status.PENDING
			existing.submitted_at = timezone.now()
			existing.verified_by = None
			existing.verified_at = None
			existing.remarks = ""
			# Update letter form data
			existing.letter_date = letter_date
			existing.letter_campus = letter_campus
			existing.letter_full_name = letter_full_name
			existing.letter_home_address = letter_home_address
			existing.letter_program = letter_program
			existing.letter_violations = letter_violations
			existing.letter_printed_name = letter_printed_name
			existing.signature_data = signature_data
			existing.save()
			messages.success(request, "Your revised letter of apology has been resubmitted successfully!")
		else:
			# Create new apology letter
			apology_letter = ApologyLetter(
				violation=violation,
				student=student,
				status=ApologyLetter.Status.PENDING,
				letter_date=letter_date,
				letter_campus=letter_campus,
				letter_full_name=letter_full_name,
				letter_home_address=letter_home_address,
				letter_program=letter_program,
				letter_violations=letter_violations,
				letter_printed_name=letter_printed_name,
				signature_data=signature_data
			)
			if apology_file:
				apology_letter.file = apology_file
			apology_letter.save()
			messages.success(request, "Your letter of apology has been submitted successfully!")
		
		return redirect("violations:student_apology")
	
	# Prepare context with violation apology status
	violations_with_status = []
	for v in violations_needing_apology:
		apology = apology_by_violation.get(v.id)
		violations_with_status.append({
			"violation": v,
			"apology": apology,
			"can_submit": apology is None or apology.status in [ApologyLetter.Status.REJECTED, ApologyLetter.Status.REVISION_NEEDED]
		})
	
	# Also include resolved violations that might have apologies
	all_apologies = ApologyLetter.objects.filter(student=student).select_related("violation").order_by("-submitted_at")
	
	ctx = {
		"student": student,
		"violations_with_status": violations_with_status,
		"all_apologies": all_apologies,
	}
	return render(request, "violations/student/apology.html", ctx)