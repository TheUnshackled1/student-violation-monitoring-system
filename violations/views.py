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
import base64
import json

from .models import (
	User, Student as StudentModel, Staff as StaffModel, OSACoordinator as OSACoordinatorModel,
	TemporaryAccessRequest, Violation, ViolationType, LoginActivity,
	ViolationDocument, ApologyLetter, StaffVerification,
	Message, StaffAlert
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
# Face Detection API (for webcam head size detection)
############################################

from django.views.decorators.csrf import csrf_exempt

@csrf_exempt
def detect_face_view(request):
	"""Detect face in image and return bounding box and head size info.
	
	Accepts POST with JSON body: { "image": "data:image/jpeg;base64,..." }
	Returns: { "faces": [...], "head_size": "small|medium|large|too_far|too_close" }
	"""
	if request.method != 'POST':
		return JsonResponse({"error": "POST required"}, status=405)
	
	try:
		import cv2
		import numpy as np
	except ImportError:
		return JsonResponse({"error": "OpenCV not installed"}, status=501)
	
	try:
		data = json.loads(request.body)
		image_data = data.get('image', '')
		
		# Remove data URL prefix if present
		if ',' in image_data:
			image_data = image_data.split(',')[1]
		
		# Decode base64 image
		image_bytes = base64.b64decode(image_data)
		nparr = np.frombuffer(image_bytes, np.uint8)
		img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
		
		if img is None:
			return JsonResponse({"error": "Could not decode image"}, status=400)
		
		# Get image dimensions
		height, width = img.shape[:2]
		frame_area = width * height
		
		# Convert to grayscale for face detection
		gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
		
		# Load Haar cascade for face detection
		cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
		face_cascade = cv2.CascadeClassifier(cascade_path)
		
		# Detect faces
		faces = face_cascade.detectMultiScale(
			gray,
			scaleFactor=1.1,
			minNeighbors=5,
			minSize=(30, 30)
		)
		
		face_list = []
		head_size = "no_face"
		head_percentage = 0
		
		for (x, y, w, h) in faces:
			face_area = w * h
			percentage = (face_area / frame_area) * 100
			
			face_list.append({
				"x": int(x),
				"y": int(y),
				"width": int(w),
				"height": int(h),
				"percentage": round(percentage, 2)
			})
			
			# Determine head size based on percentage of frame
			# Ideal for ID photo: face should be 15-35% of frame
			if percentage < 5:
				head_size = "too_far"
			elif percentage < 15:
				head_size = "small"
			elif percentage <= 35:
				head_size = "ideal"
			elif percentage <= 50:
				head_size = "large"
			else:
				head_size = "too_close"
			
			head_percentage = percentage
		
		return JsonResponse({
			"success": True,
			"faces": face_list,
			"face_count": len(face_list),
			"head_size": head_size,
			"head_percentage": round(head_percentage, 2),
			"frame_width": width,
			"frame_height": height,
			"guidance": get_head_size_guidance(head_size)
		})
		
	except json.JSONDecodeError:
		return JsonResponse({"error": "Invalid JSON"}, status=400)
	except Exception as e:
		return JsonResponse({"error": str(e)}, status=500)


def get_head_size_guidance(head_size):
	"""Return user-friendly guidance based on head size detection."""
	guidance = {
		"no_face": "No face detected. Please position your face in front of the camera.",
		"too_far": "You are too far from the camera. Please move closer.",
		"small": "Move a bit closer to the camera for better detection.",
		"ideal": "Perfect! Your position is ideal for the photo. Stay still and smile!",
		"large": "You are a bit close. Move back slightly.",
		"too_close": "You are too close to the camera. Please move back."
	}
	return guidance.get(head_size, "Adjust your position.")


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


@role_required({User.Role.STUDENT})
def student_update_profile_view(request):
	"""Student can update their profile photo, contact, guardian info, and email."""
	if request.method != 'POST':
		return JsonResponse({'success': False, 'error': 'Invalid request method'})
	
	try:
		student = getattr(request.user, "student_profile", None)
		if not student:
			return JsonResponse({'success': False, 'error': 'Student profile not found'})
		
		# Update contact number
		contact_number = request.POST.get('contact_number', '').strip()
		if contact_number:
			student.contact_number = contact_number
		
		# Update guardian name
		guardian_name = request.POST.get('guardian_name', '').strip()
		if guardian_name:
			student.guardian_name = guardian_name
		
		# Update guardian contact
		guardian_contact = request.POST.get('guardian_contact', '').strip()
		if guardian_contact:
			student.guardian_contact = guardian_contact
		
		# Update email (on User model)
		email = request.POST.get('email', '').strip()
		if email and email != request.user.email:
			# Check if email is already taken
			if User.objects.filter(email=email).exclude(pk=request.user.pk).exists():
				return JsonResponse({'success': False, 'error': 'This email is already in use'})
			request.user.email = email
			request.user.save(update_fields=['email'])
		
		# Update profile image
		if 'profile_image' in request.FILES:
			profile_image = request.FILES['profile_image']
			# Validate file size (5MB max)
			if profile_image.size > 5 * 1024 * 1024:
				return JsonResponse({'success': False, 'error': 'Image must be less than 5MB'})
			# Validate file type
			allowed_types = ['image/jpeg', 'image/png', 'image/jpg']
			if profile_image.content_type not in allowed_types:
				return JsonResponse({'success': False, 'error': 'Only JPG and PNG images are allowed'})
			# Delete old image if exists
			if student.profile_image:
				student.profile_image.delete(save=False)
			student.profile_image = profile_image
		
		student.save()
		
		return JsonResponse({'success': True, 'message': 'Profile updated successfully'})
	except Exception as e:
		return JsonResponse({'success': False, 'error': str(e)})


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
	# Staff alerts for students who reached violation threshold
	staff_alerts = StaffAlert.objects.select_related("student__user", "triggered_violation").filter(
		resolved=False
	).order_by("-created_at")
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
		"staff_alerts": staff_alerts,
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


@role_required({User.Role.OSA_COORDINATOR})
def faculty_activity_logs_view(request):
	"""
	OSA Coordinator: View all activity logs across the system.
	Shows activities from Staff, Students, Guards, and Formators.
	"""
	from .models import ActivityLog
	
	# Get filter parameters
	user_role = request.GET.get('role', 'all')
	action_filter = request.GET.get('action', 'all')
	date_from = request.GET.get('date_from', '')
	date_to = request.GET.get('date_to', '')
	search_query = request.GET.get('search', '')
	
	# Base queryset - all activity logs
	logs = ActivityLog.objects.select_related(
		'user', 'related_student', 'related_student__user', 
		'related_violation', 'related_apology'
	).order_by('-timestamp')
	
	# Filter by user role
	if user_role == 'staff':
		logs = logs.filter(user__role=User.Role.STAFF)
	elif user_role == 'student':
		logs = logs.filter(user__role=User.Role.STUDENT)
	elif user_role == 'osa_coordinator':
		logs = logs.filter(user__role=User.Role.OSA_COORDINATOR)
	elif user_role == 'guard':
		logs = logs.filter(guard_code__isnull=False).exclude(guard_code='')
	elif user_role == 'formator':
		logs = logs.filter(formator_code__isnull=False).exclude(formator_code='')
	
	# Filter by action type
	if action_filter != 'all':
		logs = logs.filter(action_type=action_filter)
	
	# Filter by date range
	if date_from:
		try:
			from datetime import datetime
			date_from_parsed = datetime.strptime(date_from, '%Y-%m-%d')
			logs = logs.filter(timestamp__date__gte=date_from_parsed)
		except ValueError:
			pass
	
	if date_to:
		try:
			from datetime import datetime
			date_to_parsed = datetime.strptime(date_to, '%Y-%m-%d')
			logs = logs.filter(timestamp__date__lte=date_to_parsed)
		except ValueError:
			pass
	
	# Search filter
	if search_query:
		logs = logs.filter(
			Q(description__icontains=search_query) |
			Q(user__username__icontains=search_query) |
			Q(user__first_name__icontains=search_query) |
			Q(user__last_name__icontains=search_query) |
			Q(guard_code__icontains=search_query) |
			Q(formator_code__icontains=search_query)
		)
	
	# Pagination
	from django.core.paginator import Paginator
	paginator = Paginator(logs, 25)  # 25 logs per page
	page_number = request.GET.get('page', 1)
	page_obj = paginator.get_page(page_number)
	
	# Get action types for filter dropdown
	action_types = ActivityLog.ActionType.choices
	
	# Summary statistics
	today = timezone.now().date()
	stats = {
		'total_logs': ActivityLog.objects.count(),
		'today_logs': ActivityLog.objects.filter(timestamp__date=today).count(),
		'staff_logs': ActivityLog.objects.filter(user__role=User.Role.STAFF).count(),
		'student_logs': ActivityLog.objects.filter(user__role=User.Role.STUDENT).count(),
		'guard_logs': ActivityLog.objects.exclude(guard_code='').count(),
		'formator_logs': ActivityLog.objects.exclude(formator_code='').count(),
	}
	
	context = {
		'page_obj': page_obj,
		'logs': page_obj,
		'action_types': action_types,
		'stats': stats,
		'current_filters': {
			'role': user_role,
			'action': action_filter,
			'date_from': date_from,
			'date_to': date_to,
			'search': search_query,
		}
	}
	
	return render(request, "violations/osa_coordinator/activity_logs.html", context)


@role_required({User.Role.OSA_COORDINATOR})
def faculty_analytics_view(request):
	"""
	OSA Coordinator Analytics Page - Full standalone page view.
	Renders the analytics dashboard page that loads data via AJAX.
	"""
	return render(request, "violations/osa_coordinator/osa_coordinator_analytics.html")


@role_required({User.Role.OSA_COORDINATOR})
def faculty_analytics_api(request):
	"""
	Analytics API for OSA Coordinator Dashboard.
	
	Returns JSON data for:
	1. Violation Trends Over Time (daily counts for last 30 days)
	2. Violation Type Breakdown (counts by Major/Minor)
	3. Violation Status Distribution
	4. Top Violation Types from ViolationType catalog
	5. Department Distribution
	
	Analytics Type: Descriptive + Basic Diagnostic
	No prediction, no complex math - just aggregation and summarization.
	"""
	from django.db.models import Count
	from django.db.models.functions import TruncDate, TruncWeek
	from datetime import timedelta
	
	today = timezone.now().date()
	thirty_days_ago = today - timedelta(days=30)
	seven_days_ago = today - timedelta(days=7)
	
	# 1. Daily Violation Trends (last 30 days)
	daily_trends = (
		Violation.objects.filter(created_at__date__gte=thirty_days_ago)
		.annotate(date=TruncDate('created_at'))
		.values('date')
		.annotate(count=Count('id'))
		.order_by('date')
	)
	
	# Fill in missing dates with zero counts
	trends_dict = {item['date']: item['count'] for item in daily_trends}
	trend_labels = []
	trend_data = []
	for i in range(30):
		date = thirty_days_ago + timedelta(days=i)
		trend_labels.append(date.strftime('%b %d'))
		trend_data.append(trends_dict.get(date, 0))
	
	# 2. Violation Type Breakdown (Major vs Minor)
	type_breakdown = (
		Violation.objects.values('type')
		.annotate(count=Count('id'))
		.order_by('type')
	)
	type_labels = []
	type_data = []
	type_colors = []
	for item in type_breakdown:
		if item['type'] == 'major':
			type_labels.append('Major Offense')
			type_colors.append('#dc2626')  # Red
		else:
			type_labels.append('Minor Offense')
			type_colors.append('#f59e0b')  # Amber
		type_data.append(item['count'])
	
	# If no data, provide defaults
	if not type_labels:
		type_labels = ['Major Offense', 'Minor Offense']
		type_data = [0, 0]
		type_colors = ['#dc2626', '#f59e0b']
	
	# 3. Violation Status Distribution
	status_breakdown = (
		Violation.objects.values('status')
		.annotate(count=Count('id'))
		.order_by('status')
	)
	status_labels = []
	status_data = []
	status_colors = []
	status_color_map = {
		'reported': ('#3b82f6', 'Reported'),
		'under_review': ('#f59e0b', 'Under Review'),
		'resolved': ('#10b981', 'Resolved'),
		'dismissed': ('#6b7280', 'Dismissed'),
	}
	for item in status_breakdown:
		color, label = status_color_map.get(item['status'], ('#9ca3af', item['status']))
		status_labels.append(label)
		status_data.append(item['count'])
		status_colors.append(color)
	
	# 4. Top Violation Types from ViolationType catalog
	top_violation_types = (
		Violation.objects.filter(violation_type__isnull=False)
		.values('violation_type__name', 'violation_type__category')
		.annotate(count=Count('id'))
		.order_by('-count')[:10]
	)
	vtype_labels = []
	vtype_data = []
	vtype_colors = []
	for item in top_violation_types:
		name = item['violation_type__name']
		if len(name) > 25:
			name = name[:22] + '...'
		vtype_labels.append(name)
		vtype_data.append(item['count'])
		if item['violation_type__category'] == 'major':
			vtype_colors.append('#dc2626')
		else:
			vtype_colors.append('#f59e0b')
	
	# 5. Department Distribution
	dept_breakdown = (
		Violation.objects.filter(student__department__isnull=False)
		.exclude(student__department='')
		.values('student__department')
		.annotate(count=Count('id'))
		.order_by('-count')[:8]
	)
	dept_labels = []
	dept_data = []
	dept_colors = ['#1a472a', '#2563eb', '#dc2626', '#f59e0b', '#10b981', '#8b5cf6', '#ec4899', '#06b6d4']
	for i, item in enumerate(dept_breakdown):
		dept = item['student__department']
		if len(dept) > 15:
			dept = dept[:12] + '...'
		dept_labels.append(dept)
		dept_data.append(item['count'])
	
	# 6. Summary Statistics
	total_violations = Violation.objects.count()
	total_major = Violation.objects.filter(type='major').count()
	total_minor = Violation.objects.filter(type='minor').count()
	total_pending = Violation.objects.filter(status__in=['reported', 'under_review']).count()
	total_resolved = Violation.objects.filter(status='resolved').count()
	this_week_count = Violation.objects.filter(created_at__date__gte=seven_days_ago).count()
	this_month_count = Violation.objects.filter(created_at__date__gte=thirty_days_ago).count()
	
	# 7. Weekly Comparison (this week vs last week)
	last_week_start = seven_days_ago - timedelta(days=7)
	last_week_count = Violation.objects.filter(
		created_at__date__gte=last_week_start,
		created_at__date__lt=seven_days_ago
	).count()
	
	if last_week_count > 0:
		week_change_percent = round(((this_week_count - last_week_count) / last_week_count) * 100, 1)
	else:
		week_change_percent = 100 if this_week_count > 0 else 0
	
	analytics_data = {
		'success': True,
		'generated_at': timezone.now().isoformat(),
		'summary': {
			'total_violations': total_violations,
			'total_major': total_major,
			'total_minor': total_minor,
			'total_pending': total_pending,
			'total_resolved': total_resolved,
			'this_week': this_week_count,
			'this_month': this_month_count,
			'week_change_percent': week_change_percent,
		},
		'trends': {
			'labels': trend_labels,
			'data': trend_data,
		},
		'type_breakdown': {
			'labels': type_labels,
			'data': type_data,
			'colors': type_colors,
		},
		'status_breakdown': {
			'labels': status_labels,
			'data': status_data,
			'colors': status_colors,
		},
		'top_violation_types': {
			'labels': vtype_labels,
			'data': vtype_data,
			'colors': vtype_colors,
		},
		'department_breakdown': {
			'labels': dept_labels,
			'data': dept_data,
			'colors': dept_colors[:len(dept_labels)],
		},
		# 8. Prescriptive Analytics - Rule-based recommendations
		'prescriptive': generate_prescriptive_recommendations(
			total_violations=total_violations,
			total_major=total_major,
			total_minor=total_minor,
			total_pending=total_pending,
			week_change_percent=week_change_percent,
			top_violation_types=list(top_violation_types),
			dept_breakdown=list(dept_breakdown),
		),
	}
	
	return JsonResponse(analytics_data)


def generate_prescriptive_recommendations(total_violations, total_major, total_minor, 
                                          total_pending, week_change_percent, 
                                          top_violation_types, dept_breakdown):
	"""
	Generate prescriptive analytics recommendations based on violation data.
	
	This function performs rule-based analysis to provide actionable recommendations
	without using predictive algorithms or automated decision-making.
	
	Returns a dictionary containing:
	- priority_actions: Immediate actions needed
	- prevention_strategies: Long-term prevention recommendations
	- department_focus: Department-specific recommendations
	- violation_insights: Insights about specific violation types
	"""
	recommendations = {
		'priority_actions': [],
		'prevention_strategies': [],
		'department_focus': [],
		'violation_insights': [],
		'summary_recommendation': '',
	}
	
	# === PRIORITY ACTIONS (Immediate concerns) ===
	
	# High pending cases
	if total_pending > 10:
		recommendations['priority_actions'].append({
			'icon': 'fa-clock',
			'severity': 'high',
			'title': 'High Volume of Pending Cases',
			'description': f'There are {total_pending} cases awaiting review. Consider scheduling a dedicated review session.',
			'action': 'Schedule case review meeting within 3 days',
		})
	elif total_pending > 5:
		recommendations['priority_actions'].append({
			'icon': 'fa-hourglass-half',
			'severity': 'medium',
			'title': 'Moderate Pending Cases',
			'description': f'{total_pending} cases are pending. Regular review recommended.',
			'action': 'Review pending cases this week',
		})
	
	# Week-over-week increase
	if week_change_percent > 50:
		recommendations['priority_actions'].append({
			'icon': 'fa-arrow-trend-up',
			'severity': 'high',
			'title': 'Significant Increase in Violations',
			'description': f'Violations increased by {week_change_percent}% compared to last week.',
			'action': 'Investigate root causes and increase monitoring',
		})
	elif week_change_percent > 20:
		recommendations['priority_actions'].append({
			'icon': 'fa-chart-line',
			'severity': 'medium',
			'title': 'Notable Increase in Violations',
			'description': f'Violations increased by {week_change_percent}% from last week.',
			'action': 'Monitor trends and identify contributing factors',
		})
	
	# Major violations ratio
	if total_violations > 0:
		major_ratio = (total_major / total_violations) * 100
		if major_ratio > 40:
			recommendations['priority_actions'].append({
				'icon': 'fa-exclamation-triangle',
				'severity': 'high',
				'title': 'High Major Offense Ratio',
				'description': f'{major_ratio:.1f}% of violations are major offenses. This requires immediate attention.',
				'action': 'Conduct disciplinary review and strengthen enforcement',
			})
		elif major_ratio > 25:
			recommendations['priority_actions'].append({
				'icon': 'fa-balance-scale',
				'severity': 'medium',
				'title': 'Elevated Major Offense Rate',
				'description': f'{major_ratio:.1f}% of violations are major offenses.',
				'action': 'Review major offense handling procedures',
			})
	
	# === PREVENTION STRATEGIES (Long-term recommendations) ===
	
	# Based on top violation types
	if top_violation_types:
		top_violation = top_violation_types[0]
		vtype_name = top_violation.get('violation_type__name', 'Unknown')
		vtype_count = top_violation.get('count', 0)
		vtype_category = top_violation.get('violation_type__category', 'minor')
		
		# Dress code related
		if any(kw in vtype_name.lower() for kw in ['uniform', 'dress', 'attire', 'id', 'identification']):
			recommendations['prevention_strategies'].append({
				'icon': 'fa-tshirt',
				'category': 'Dress Code',
				'title': 'Strengthen Dress Code Awareness',
				'description': f'"{vtype_name}" is the most common violation ({vtype_count} cases).',
				'actions': [
					'Post visual reminders of dress code policy at entrances',
					'Conduct orientation on proper uniform/attire guidelines',
					'Consider peer reminder programs before class hours',
				]
			})
		
		# Attendance/tardiness related
		elif any(kw in vtype_name.lower() for kw in ['late', 'tardy', 'absent', 'attendance', 'cutting']):
			recommendations['prevention_strategies'].append({
				'icon': 'fa-clock',
				'category': 'Attendance',
				'title': 'Address Attendance Issues',
				'description': f'"{vtype_name}" accounts for {vtype_count} violations.',
				'actions': [
					'Review class scheduling for potential conflicts',
					'Implement early warning system for chronic absenteeism',
					'Engage with students showing attendance patterns',
				]
			})
		
		# Behavioral issues
		elif any(kw in vtype_name.lower() for kw in ['disrespect', 'misconduct', 'behavior', 'fight', 'bully']):
			recommendations['prevention_strategies'].append({
				'icon': 'fa-users',
				'category': 'Behavior',
				'title': 'Behavioral Intervention Needed',
				'description': f'"{vtype_name}" is a recurring issue ({vtype_count} cases).',
				'actions': [
					'Implement conflict resolution workshops',
					'Establish peer mediation programs',
					'Increase counselor availability',
				]
			})
		
		# Smoking/substance related
		elif any(kw in vtype_name.lower() for kw in ['smok', 'vape', 'alcohol', 'drug', 'substance']):
			recommendations['prevention_strategies'].append({
				'icon': 'fa-ban-smoking',
				'category': 'Health & Safety',
				'title': 'Substance-Related Violations',
				'description': f'"{vtype_name}" requires health-focused intervention ({vtype_count} cases).',
				'actions': [
					'Coordinate with health services for awareness campaigns',
					'Strengthen enforcement in designated areas',
					'Offer counseling resources for affected students',
				]
			})
		
		# Default recommendation
		else:
			recommendations['prevention_strategies'].append({
				'icon': 'fa-lightbulb',
				'category': 'General',
				'title': f'Address "{vtype_name[:30]}..."' if len(vtype_name) > 30 else f'Address "{vtype_name}"',
				'description': f'This violation type has {vtype_count} recorded cases.',
				'actions': [
					'Review policy clarity and student awareness',
					'Conduct targeted information sessions',
					'Monitor for patterns and contributing factors',
				]
			})
	
	# === DEPARTMENT-SPECIFIC FOCUS ===
	
	if dept_breakdown:
		# Top department with most violations
		top_dept = dept_breakdown[0]
		dept_name = top_dept.get('student__department', 'Unknown')
		dept_count = top_dept.get('count', 0)
		
		recommendations['department_focus'].append({
			'icon': 'fa-building',
			'department': dept_name,
			'violation_count': dept_count,
			'recommendation': f'Coordinate with {dept_name} administration for targeted intervention',
			'actions': [
				f'Schedule meeting with {dept_name} dean/coordinator',
				'Review department-specific violation patterns',
				'Consider department-level awareness programs',
			]
		})
		
		# If there's a significant gap between departments
		if len(dept_breakdown) > 1:
			second_dept = dept_breakdown[1]
			if dept_count > second_dept.get('count', 0) * 2:
				recommendations['department_focus'][0]['priority'] = 'high'
				recommendations['department_focus'][0]['note'] = f'{dept_name} has significantly more violations than other departments'
	
	# === VIOLATION INSIGHTS ===
	
	# Minor to major conversion risk
	if total_minor > 0:
		students_at_risk = StudentModel.objects.annotate(
			minor_count=Count('violations', filter=Q(violations__type='minor'))
		).filter(minor_count__gte=2).count()
		
		if students_at_risk > 0:
			recommendations['violation_insights'].append({
				'icon': 'fa-user-clock',
				'title': 'Students Approaching Major Threshold',
				'description': f'{students_at_risk} student(s) have 2+ minor violations (3 minors = 1 major).',
				'action': 'Consider preventive counseling for at-risk students',
			})
	
	# Resolution rate insight
	if total_violations > 0:
		from .models import Violation as ViolationModel
		resolved_count = ViolationModel.objects.filter(status='resolved').count()
		resolution_rate = (resolved_count / total_violations) * 100
		
		if resolution_rate < 50:
			recommendations['violation_insights'].append({
				'icon': 'fa-tasks',
				'title': 'Low Resolution Rate',
				'description': f'Only {resolution_rate:.1f}% of cases are resolved.',
				'action': 'Review case processing workflow for bottlenecks',
			})
		elif resolution_rate > 80:
			recommendations['violation_insights'].append({
				'icon': 'fa-check-double',
				'title': 'Strong Resolution Rate',
				'description': f'{resolution_rate:.1f}% resolution rate indicates effective case management.',
				'action': 'Maintain current practices and document best approaches',
			})
	
	# === SUMMARY RECOMMENDATION ===
	
	if not recommendations['priority_actions']:
		recommendations['summary_recommendation'] = 'Current violation levels are manageable. Continue regular monitoring and maintain preventive programs.'
	elif any(a['severity'] == 'high' for a in recommendations['priority_actions']):
		recommendations['summary_recommendation'] = 'Immediate attention required. Review priority actions and schedule intervention meetings within this week.'
	else:
		recommendations['summary_recommendation'] = 'Some areas need attention. Address medium-priority items within the next two weeks.'
	
	return recommendations


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
	# Staff alerts for students who reached violation threshold
	staff_alerts = StaffAlert.objects.select_related("student__user", "triggered_violation").filter(
		resolved=False
	).order_by("-created_at")
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
		"staff_alerts": staff_alerts,
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
def staff_check_student_view(request):
	"""Staff: AJAX endpoint to check if a student exists in the database."""
	student_id = request.GET.get('student_id', '').strip()
	
	if not student_id:
		return JsonResponse({'error': 'Student ID is required'}, status=400)
	
	try:
		student = StudentModel.objects.select_related('user').get(student_id__iexact=student_id)
		return JsonResponse({
			'exists': True,
			'student_id': student.student_id,
			'student_name': student.user.get_full_name() or student.student_id,
			'program': student.program,
			'year_level': student.year_level,
		})
	except StudentModel.DoesNotExist:
		return JsonResponse({'exists': False})


@role_required({User.Role.STAFF})
def staff_violation_create_view(request):
	"""Staff: Create a new violation record from physical reports."""
	if request.method == 'POST':
		student_id = request.POST.get('student_id', '').strip()
		description = request.POST.get('description', '').strip()
		violation_type = request.POST.get('type', '')
		violation_type_id = request.POST.get('violation_type_id', '')
		other_violation = request.POST.get('other_violation', '').strip()
		other_category = request.POST.get('other_category', '')
		type_from_other = request.POST.get('type_from_other', '')  # Hidden field from JS
		location = request.POST.get('location', '').strip()
		incident_date = request.POST.get('incident_date', '')
		incident_time = request.POST.get('incident_time', '')
		
		# New student registration fields
		first_name = request.POST.get('first_name', '').strip()
		last_name = request.POST.get('last_name', '').strip()
		suffix = request.POST.get('suffix', '').strip()
		email = request.POST.get('email', '').strip()
		contact_number = request.POST.get('contact_number', '').strip()
		program = request.POST.get('program', '').strip()
		year_level = request.POST.get('year_level', '1').strip()
		guardian_name = request.POST.get('guardian_name', '').strip()
		guardian_contact = request.POST.get('guardian_contact', '').strip()
		
		# Validate student ID is 8 digits
		if not student_id.isdigit() or len(student_id) != 8:
			messages.error(request, "Student ID must be exactly 8 digits.")
			return redirect('violations:staff_violation_create')
		
		# Check if student exists by student_id
		student = StudentModel.objects.filter(student_id__iexact=student_id).first()
		student_created = False
		
		if not student:
			# Auto-register new student if name is provided
			if not first_name or not last_name:
				messages.error(request, f"Student with ID '{student_id}' not found. Please provide First Name and Last Name to register.")
				return redirect('violations:staff_violation_create')
			
			# Validate contact numbers are 11 digits if provided
			if contact_number and (not contact_number.isdigit() or len(contact_number) != 11):
				messages.error(request, "Contact number must be exactly 11 digits.")
				return redirect('violations:staff_violation_create')
			
			if guardian_contact and (not guardian_contact.isdigit() or len(guardian_contact) != 11):
				messages.error(request, "Guardian contact must be exactly 11 digits.")
				return redirect('violations:staff_violation_create')
			
			# Create a User account for the new student
			username = student_id.replace('-', '').lower()
			
			# Check if user already exists with this username
			existing_user = User.objects.filter(username=username).first()
			
			if existing_user:
				# Check if this user already has a student profile
				if hasattr(existing_user, 'student_profile'):
					# User already has a student profile - use it
					student = existing_user.student_profile
					messages.info(request, f"Found existing student record for user '{username}'.")
				else:
					# User exists but no student profile - create one
					try:
						year_level_int = int(year_level)
					except (ValueError, TypeError):
						year_level_int = 1
					
					student = StudentModel.objects.create(
						user=existing_user,
						student_id=student_id,
						suffix=suffix,
						program=program,
						year_level=year_level_int,
						year_level_assigned_at=timezone.now(),
						department=program,
						contact_number=contact_number,
						guardian_name=guardian_name,
						guardian_contact=guardian_contact,
						enrollment_status='Active'
					)
					student_created = True
			else:
				# Create new user and student profile
				full_last_name = f"{last_name} {suffix}".strip() if suffix else last_name
				user = User.objects.create_user(
					username=username,
					first_name=first_name,
					last_name=full_last_name,
					password=student_id,  # Default password is student ID
					email=email or f"{username}@student.chmsu.edu.ph",
					role=User.Role.STUDENT
				)
				
				# Create the Student profile
				try:
					year_level_int = int(year_level)
				except (ValueError, TypeError):
					year_level_int = 1
				
				student = StudentModel.objects.create(
					user=user,
					student_id=student_id,
					suffix=suffix,
					program=program,
					year_level=year_level_int,
					year_level_assigned_at=timezone.now(),
					department=program,
					contact_number=contact_number,
					guardian_name=guardian_name,
					guardian_contact=guardian_contact,
					enrollment_status='Active'
				)
				student_created = True
		
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
		
		# Get violation type from catalog OR use other violation
		catalog_violation_type = None
		if violation_type_id:
			catalog_violation_type = ViolationType.objects.filter(id=violation_type_id, is_active=True).first()
			# Auto-set the severity based on violation type category
			if catalog_violation_type:
				violation_type = catalog_violation_type.category
		elif other_violation:
			# Using "Other Violation" - prepend to description
			description = f"[Other Violation: {other_violation}]\n\n{description}" if description else f"[Other Violation: {other_violation}]"
			# Use category from radio button (passed via hidden field)
			violation_type = type_from_other or other_category or Violation.Severity.MINOR
		
		# Default to minor if no type selected
		if not violation_type:
			violation_type = Violation.Severity.MINOR
		
		# Create violation
		violation = Violation.objects.create(
			student=student,
			reported_by=request.user,
			description=description,
			type=violation_type,
			violation_type=catalog_violation_type,
			location=location or 'Not specified',
			incident_at=incident_at,
			status=Violation.Status.REPORTED,
		)
		
		# Log the activity
		from .models import ActivityLog
		student_name = student.user.get_full_name() or student.student_id
		ActivityLog.log_activity(
			action_type=ActivityLog.ActionType.VIOLATION_CREATED,
			description=f"Created violation #{violation.id} for {student_name}: {description[:100]}..." if len(description) > 100 else f"Created violation #{violation.id} for {student_name}: {description}",
			request=request,
			user=request.user,
			related_student=student,
			related_violation=violation
		)
		
		# Track offense frequency for this student
		offense_count = Violation.objects.filter(student=student).count()
		
		# Build success message
		student_name = student.user.get_full_name() or student.student_id
		if student_created:
			messages.success(request, f"Violation #{violation.id} created successfully. New student \"{student_name}\" ({student_id}) was automatically registered. This is offense #{offense_count}.")
		else:
			messages.success(request, f"Violation #{violation.id} created successfully. This is offense #{offense_count} for {student_name}.")
		return redirect('violations:staff_violations_list')
	
	# GET request
	students = StudentModel.objects.select_related('user').all().order_by('student_id')
	violation_types = ViolationType.objects.filter(is_active=True).order_by('category', 'name')
	ctx = {
		'students': students,
		'type_choices': Violation.Severity.choices,
		'violation_types': violation_types,
	}
	return render(request, 'violations/staff/violation_form.html', ctx)


@role_required({User.Role.STAFF})
def staff_violation_edit_view(request, violation_id):
	"""Staff: Edit an existing violation record."""
	violation = get_object_or_404(Violation.objects.select_related('student', 'student__user'), id=violation_id)
	
	if request.method == 'POST':
		description = request.POST.get('description', '').strip()
		violation_type = request.POST.get('type', violation.type)
		violation_type_id = request.POST.get('violation_type_id', '')
		other_violation = request.POST.get('other_violation', '').strip()
		other_category = request.POST.get('other_category', '')
		status = request.POST.get('status', violation.status)
		location = request.POST.get('location', violation.location)
		incident_date = request.POST.get('incident_date', '')
		incident_time = request.POST.get('incident_time', '')
		
		violation.description = description
		violation.location = location
		violation.status = status
		
		# Get violation type from catalog OR use other violation
		if violation_type_id:
			catalog_violation_type = ViolationType.objects.filter(id=violation_type_id, is_active=True).first()
			if catalog_violation_type:
				violation.violation_type = catalog_violation_type
				violation.type = catalog_violation_type.category
		elif other_violation:
			# Using "Other Violation" - prepend to description if not already there
			if not description.startswith('[Other Violation:'):
				violation.description = f"[Other Violation: {other_violation}]\n\n{description}" if description else f"[Other Violation: {other_violation}]"
			violation.violation_type = None
			violation.type = other_category or violation.type
		else:
			violation.violation_type = None
			violation.type = violation_type
		
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
		
		# Log the activity
		from .models import ActivityLog
		student_name = violation.student.user.get_full_name() or violation.student.student_id
		ActivityLog.log_activity(
			action_type=ActivityLog.ActionType.VIOLATION_UPDATED,
			description=f"Updated violation #{violation.id} for {student_name}",
			request=request,
			user=request.user,
			related_student=violation.student,
			related_violation=violation
		)
		
		messages.success(request, f"Violation #{violation.id} updated successfully.")
		return redirect('violations:staff_violations_list')
	
	# GET request
	existing_docs = ViolationDocument.objects.filter(violation=violation)
	violation_types = ViolationType.objects.filter(is_active=True).order_by('category', 'name')
	ctx = {
		'violation': violation,
		'existing_docs': existing_docs,
		'type_choices': Violation.Severity.choices,
		'status_choices': Violation.Status.choices,
		'violation_types': violation_types,
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
	verifications = StaffVerification.objects.filter(violation=violation).select_related('staff')
	
	# Get offense history for the student
	student_violations = Violation.objects.filter(student=violation.student).order_by('-created_at')
	offense_number = list(student_violations).index(violation) + 1 if violation in student_violations else 1
	total_offenses = student_violations.count()
	
	ctx = {
		'violation': violation,
		'documents': documents,
		'apology_letters': apology_letters,
		'verifications': verifications,
		'offense_number': offense_number,
		'total_offenses': total_offenses,
		'student_violations': student_violations[:5],
	}
	return render(request, 'violations/staff/violation_detail.html', ctx)


@role_required({User.Role.STAFF})
def staff_verify_violation_view(request, violation_id):
	"""Staff: Verify/validate a violation record."""
	violation = get_object_or_404(Violation.objects.select_related('student', 'student__user'), id=violation_id)
	
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
		from .models import ActivityLog
		student_name = violation.student.user.get_full_name() or violation.student.student_id
		
		if action == 'verified':
			if violation.status == Violation.Status.REPORTED:
				violation.status = Violation.Status.UNDER_REVIEW
				violation.save()
			ActivityLog.log_activity(
				action_type=ActivityLog.ActionType.VIOLATION_VERIFIED,
				description=f"Verified violation #{violation.id} for {student_name}",
				request=request,
				user=request.user,
				related_student=violation.student,
				related_violation=violation
			)
			messages.success(request, f"Violation #{violation.id} has been verified.")
		elif action == 'correction_needed':
			ActivityLog.log_activity(
				action_type=ActivityLog.ActionType.VIOLATION_UPDATED,
				description=f"Marked violation #{violation.id} for correction. Notes: {notes}",
				request=request,
				user=request.user,
				related_student=violation.student,
				related_violation=violation
			)
			messages.warning(request, f"Violation #{violation.id} marked for correction.")
		elif action == 'escalated':
			ActivityLog.log_activity(
				action_type=ActivityLog.ActionType.VIOLATION_UPDATED,
				description=f"Escalated violation #{violation.id} to supervisor. Notes: {notes}",
				request=request,
				user=request.user,
				related_student=violation.student,
				related_violation=violation
			)
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
	from .models import ActivityLog
	letter = get_object_or_404(ApologyLetter.objects.select_related('student', 'violation'), id=letter_id)
	
	if request.method == 'POST':
		action = request.POST.get('action', 'approved')
		remarks = request.POST.get('remarks', '').strip()
		
		letter.status = action
		letter.verified_by = request.user
		letter.verified_at = timezone.now()
		letter.remarks = remarks
		letter.save()
		
		# Log the activity
		student_name = letter.student.user.get_full_name() or letter.student.student_id
		if action == ApologyLetter.Status.APPROVED:
			ActivityLog.log_activity(
				user=request.user,
				action_type=ActivityLog.ActionType.APOLOGY_APPROVED,
				description=f"Approved apology letter from {student_name} for violation #{letter.violation.id}",
				request=request,
				related_apology=letter,
				related_student=letter.student,
				related_violation=letter.violation
			)
			messages.success(request, f"Apology letter from {student_name} has been approved.")
		elif action == ApologyLetter.Status.REVISION_NEEDED:
			ActivityLog.log_activity(
				user=request.user,
				action_type=ActivityLog.ActionType.APOLOGY_REVISION,
				description=f"Requested revision on apology letter from {student_name}. Remarks: {remarks}",
				request=request,
				related_apology=letter,
				related_student=letter.student,
				related_violation=letter.violation
			)
			messages.warning(request, f"Apology letter from {student_name} requires revision.")
		else:
			ActivityLog.log_activity(
				user=request.user,
				action_type=ActivityLog.ActionType.APOLOGY_REJECTED,
				description=f"Rejected apology letter from {student_name}. Remarks: {remarks}",
				request=request,
				related_apology=letter,
				related_student=letter.student,
				related_violation=letter.violation
			)
			messages.error(request, f"Apology letter from {student_name} has been rejected.")
		
		return redirect('violations:staff_apology_letters')
	
	ctx = {'letter': letter}
	return render(request, 'violations/staff/verify_apology.html', ctx)


@role_required({User.Role.STAFF})
def staff_send_to_formator_view(request, letter_id):
	"""Staff: Send apology letter to Student Formator for verification."""
	from .models import ActivityLog
	letter = get_object_or_404(ApologyLetter.objects.select_related('student', 'student__user', 'violation'), id=letter_id)
	
	if request.method == 'POST':
		letter.formator_status = 'pending'
		letter.sent_to_formator_at = timezone.now()
		letter.sent_to_formator_by = request.user
		letter.save()
		
		# Log the activity
		student_name = letter.student.user.get_full_name() or letter.student.student_id
		ActivityLog.log_activity(
			user=request.user,
			action_type=ActivityLog.ActionType.APOLOGY_SENT_FORMATOR,
			description=f"Sent apology letter from {student_name} to Student Formator for verification",
			request=request,
			related_apology=letter,
			related_student=letter.student,
			related_violation=letter.violation
		)
		
		messages.success(request, f"Apology letter has been sent to the Student Formator for verification.")
		return redirect('violations:staff_verify_apology', letter_id=letter.id)
	
	return redirect('violations:staff_verify_apology', letter_id=letter.id)


@role_required({User.Role.STAFF})
def staff_reports_view(request):
	"""Staff: Generate and view violation reports with comprehensive statistics."""
	from datetime import timedelta
	
	# Date range filters
	start_date = request.GET.get('start_date', '')
	end_date = request.GET.get('end_date', '')
	report_type = request.GET.get('report_type', 'summary')
	
	# Parse dates
	start_date_obj = None
	end_date_obj = None
	
	violations = Violation.objects.select_related('student', 'student__user', 'reported_by', 'violation_type')
	
	if start_date:
		try:
			start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")
			violations = violations.filter(incident_at__gte=timezone.make_aware(start_date_obj))
		except ValueError:
			pass
	
	if end_date:
		try:
			end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")
			violations = violations.filter(incident_at__lte=timezone.make_aware(end_date_obj))
		except ValueError:
			pass
	
	# ============================================
	# BASIC VIOLATION STATISTICS
	# ============================================
	total_violations = violations.count()
	by_type = violations.values('type').annotate(count=Count('id'))
	by_status = violations.values('status').annotate(count=Count('id'))
	
	# Status counts
	pending_count = violations.filter(status=Violation.Status.REPORTED).count()
	in_progress_count = violations.filter(status=Violation.Status.UNDER_REVIEW).count()
	resolved_count = violations.filter(status=Violation.Status.RESOLVED).count()
	
	# Resolution rate
	resolution_rate = round((resolved_count / total_violations * 100), 1) if total_violations > 0 else 0
	
	# Average resolution time (for resolved violations)
	# Using updated_at as proxy for resolution date since resolved_at doesn't exist
	avg_resolution_days = 0
	resolved_violations = violations.filter(status=Violation.Status.RESOLVED)
	if resolved_violations.exists():
		total_days = 0
		count = 0
		for v in resolved_violations:
			if v.updated_at and v.incident_at:
				delta = v.updated_at - v.incident_at
				total_days += delta.days
				count += 1
		avg_resolution_days = round(total_days / count, 1) if count > 0 else 0
	
	# ============================================
	# APOLOGY LETTER STATISTICS
	# ============================================
	apology_letters = ApologyLetter.objects.select_related('student', 'violation')
	if start_date_obj:
		apology_letters = apology_letters.filter(submitted_at__gte=timezone.make_aware(start_date_obj))
	if end_date_obj:
		apology_letters = apology_letters.filter(submitted_at__lte=timezone.make_aware(end_date_obj))
	
	total_apologies = apology_letters.count()
	apology_pending = apology_letters.filter(status=ApologyLetter.Status.PENDING).count()
	apology_approved = apology_letters.filter(status=ApologyLetter.Status.APPROVED).count()
	apology_rejected = apology_letters.filter(status=ApologyLetter.Status.REJECTED).count()
	apology_revision = apology_letters.filter(status=ApologyLetter.Status.REVISION_NEEDED).count()
	apology_formator_pending = apology_letters.filter(formator_status='pending').count()
	apology_formator_signed = apology_letters.filter(formator_status='signed').count()
	
	# ============================================
	# SEVERITY DISTRIBUTION
	# ============================================
	severity_stats = []
	severity_colors = {
		'minor': '#f59e0b',
		'major': '#ef4444',
		'grave': '#7c3aed'
	}
	
	for severity_choice in Violation.Severity.choices:
		severity_value = severity_choice[0]
		severity_label = severity_choice[1]
		count = violations.filter(type=severity_value).count()
		percentage = round((count / total_violations * 100), 1) if total_violations > 0 else 0
		severity_stats.append({
			'severity': severity_label,
			'severity_key': severity_value,
			'count': count,
			'percentage': percentage,
			'color': severity_colors.get(severity_value, '#6b7280')
		})
	
	# ============================================
	# PROGRAM/DEPARTMENT BREAKDOWN
	# ============================================
	program_stats = violations.values('student__program').annotate(
		count=Count('id')
	).order_by('-count')[:10]
	
	program_breakdown = []
	program_colors = ['#1a472a', '#2d6a3f', '#059669', '#10b981', '#34d399', '#6ee7b7', '#3b82f6', '#6366f1', '#8b5cf6', '#a855f7']
	for i, prog in enumerate(program_stats):
		program_name = prog['student__program'] or 'Unknown'
		count = prog['count']
		percentage = round((count / total_violations * 100), 1) if total_violations > 0 else 0
		program_breakdown.append({
			'program': program_name,
			'count': count,
			'percentage': percentage,
			'color': program_colors[i % len(program_colors)]
		})
	
	# ============================================
	# YEAR LEVEL ANALYSIS
	# ============================================
	year_level_stats = violations.values('student__year_level').annotate(
		count=Count('id')
	).order_by('student__year_level')
	
	year_level_breakdown = []
	max_year_count = max([yl['count'] for yl in year_level_stats], default=1)
	for yl in year_level_stats:
		year = yl['student__year_level']
		count = yl['count']
		year_label = f"Year {year}" if year else 'Unknown'
		percentage = round((count / max_year_count * 100), 1) if max_year_count > 0 else 0
		year_level_breakdown.append({
			'year': year_label,
			'year_num': year or 0,
			'count': count,
			'percentage': percentage
		})
	
	# ============================================
	# VIOLATION TYPE BREAKDOWN
	# ============================================
	violation_type_stats = violations.exclude(violation_type__isnull=True).values(
		'violation_type__name', 'violation_type__category'
	).annotate(count=Count('id')).order_by('-count')[:10]
	
	violation_types = []
	type_colors = ['#1a472a', '#2d5a3f', '#3d8b5f', '#4da67f', '#5dc19f', '#3b82f6', '#6366f1', '#8b5cf6', '#ec4899', '#f43f5e']
	for i, vt in enumerate(violation_type_stats):
		type_name = vt['violation_type__name'] or 'Unknown'
		count = vt['count']
		percentage = round((count / total_violations * 100), 1) if total_violations > 0 else 0
		violation_types.append({
			'type': type_name,
			'severity': vt['violation_type__category'],
			'count': count,
			'percentage': percentage,
			'color': type_colors[i % len(type_colors)]
		})
	
	# ============================================
	# TOP OFFENDERS
	# ============================================
	top_offenders = (
		violations.values('student__student_id', 'student__user__first_name', 'student__user__last_name')
		.annotate(count=Count('id'))
		.order_by('-count')[:10]
	)
	
	# ============================================
	# MONTHLY TREND (Last 6 months)
	# ============================================
	monthly_trend = []
	six_months_ago = timezone.now() - timedelta(days=180)
	monthly_data = (
		violations.filter(incident_at__gte=six_months_ago)
		.extra(select={'month': "strftime('%%Y-%%m', incident_at)"})
		.values('month')
		.annotate(count=Count('id'))
		.order_by('month')
	)
	
	max_monthly_count = max([m['count'] for m in monthly_data], default=1)
	for m in monthly_data:
		if m['month']:
			try:
				month_date = datetime.strptime(m['month'], '%Y-%m')
				month_label = month_date.strftime('%b')
			except:
				month_label = m['month']
			height = int((m['count'] / max_monthly_count) * 100) if max_monthly_count > 0 else 0
			monthly_trend.append({
				'month': month_label,
				'full_month': m['month'],
				'count': m['count'],
				'height': max(height, 5)  # Minimum 5% height for visibility
			})
	
	# ============================================
	# RECENT VIOLATIONS
	# ============================================
	recent_violations = violations.order_by('-incident_at')[:10]
	
	ctx = {
		'start_date': start_date,
		'end_date': end_date,
		'report_type': report_type,
		
		# Basic stats
		'total_violations': total_violations,
		'pending_count': pending_count,
		'in_progress_count': in_progress_count,
		'resolved_count': resolved_count,
		'resolution_rate': resolution_rate,
		'avg_resolution_days': avg_resolution_days,
		
		# Apology letter stats
		'total_apologies': total_apologies,
		'apology_pending': apology_pending,
		'apology_approved': apology_approved,
		'apology_rejected': apology_rejected,
		'apology_revision': apology_revision,
		'apology_formator': apology_formator_pending,
		'apology_signed': apology_formator_signed,
		
		# Breakdowns
		'severity_stats': severity_stats,
		'program_breakdown': program_breakdown,
		'year_level_breakdown': year_level_breakdown,
		'violation_types': violation_types,
		'top_offenders': top_offenders,
		'monthly_trend': monthly_trend,
		
		# Data
		'by_type': {item['type']: item['count'] for item in by_type},
		'by_status': {item['status']: item['count'] for item in by_status},
		'recent_violations': recent_violations,
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
def staff_send_report_view(request):
	"""Staff: Send violation report summary to OSA Coordinator."""
	if request.method != 'POST':
		return redirect('violations:staff_reports')
	
	start_date = request.POST.get('start_date', '')
	end_date = request.POST.get('end_date', '')
	message_content = request.POST.get('message', '').strip()
	
	# Get statistics for the report
	violations = Violation.objects.all()
	apology_letters = ApologyLetter.objects.all()
	
	# Apply date filters
	if start_date:
		try:
			start_dt = datetime.strptime(start_date, "%Y-%m-%d")
			violations = violations.filter(incident_at__gte=timezone.make_aware(start_dt))
			apology_letters = apology_letters.filter(submitted_at__gte=timezone.make_aware(start_dt))
		except ValueError:
			pass
	
	if end_date:
		try:
			end_dt = datetime.strptime(end_date, "%Y-%m-%d")
			violations = violations.filter(incident_at__lte=timezone.make_aware(end_dt))
			apology_letters = apology_letters.filter(submitted_at__lte=timezone.make_aware(end_dt))
		except ValueError:
			pass
	
	# Calculate statistics
	total_violations = violations.count()
	pending_count = violations.filter(status=Violation.Status.REPORTED).count()
	in_progress_count = violations.filter(status=Violation.Status.UNDER_REVIEW).count()
	resolved_count = violations.filter(status=Violation.Status.RESOLVED).count()
	resolution_rate = round((resolved_count / total_violations * 100), 1) if total_violations > 0 else 0
	total_apologies = apology_letters.count()
	
	# Build the report message
	period_text = ""
	if start_date and end_date:
		period_text = f"Period: {start_date} to {end_date}"
	else:
		period_text = f"As of {timezone.now().strftime('%B %d, %Y')}"
	
	report_message = f"""📊 VIOLATION REPORT SUMMARY
{period_text}

📈 Statistics:
• Total Violations: {total_violations}
• Pending: {pending_count}
• In Progress: {in_progress_count}
• Resolved: {resolved_count}
• Resolution Rate: {resolution_rate}%
• Apology Letters: {total_apologies}
"""
	
	if message_content:
		report_message += f"""
📝 Staff Notes:
{message_content}
"""
	
	report_message += f"""
—
Sent by: {request.user.get_full_name() or request.user.username}
Generated: {timezone.now().strftime('%B %d, %Y at %I:%M %p')}"""
	
	# Find all OSA Coordinators
	coordinators = User.objects.filter(role=User.Role.OSA_COORDINATOR)
	
	if not coordinators.exists():
		messages.error(request, "No OSA Coordinators found in the system.")
		return redirect('violations:staff_reports')
	
	# Send message to all coordinators
	sent_count = 0
	for coordinator in coordinators:
		Message.objects.create(
			sender=request.user,
			receiver=coordinator,
			content=report_message
		)
		sent_count += 1
	
	# Log the activity
	ActivityLog.log_activity(
		action='report_sent',
		description=f"Sent violation report summary to {sent_count} coordinator(s). {period_text}",
		performed_by=request.user
	)
	
	messages.success(request, f"Report sent successfully to {sent_count} OSA Coordinator(s).")
	return redirect('violations:staff_reports')


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
		first_name = request.POST.get('first_name', '').strip()
		last_name = request.POST.get('last_name', '').strip()
		suffix = request.POST.get('suffix', '').strip()
		email = request.POST.get('email', '').strip()
		contact_number = request.POST.get('contact_number', '').strip()
		program = request.POST.get('program', '').strip()
		year_level = request.POST.get('year_level', '').strip()
		guardian_name = request.POST.get('guardian_name', '').strip()
		guardian_contact = request.POST.get('guardian_contact', '').strip()
		
		# Use student_id as username (students login with student ID)
		username = student_id
		
		# Validate required fields
		if not all([student_id, first_name, last_name, program, year_level]):
			messages.error(request, "Please fill in all required fields.")
			return redirect('violations:staff_dashboard')
		
		# Validate student ID is 8 digits
		if not student_id.isdigit() or len(student_id) != 8:
			messages.error(request, "Student ID must be exactly 8 digits.")
			return redirect('violations:staff_dashboard')
		
		# Validate contact numbers are 11 digits (if provided)
		if contact_number and (not contact_number.isdigit() or len(contact_number) != 11):
			messages.error(request, "Contact number must be exactly 11 digits.")
			return redirect('violations:staff_dashboard')
		
		if guardian_contact and (not guardian_contact.isdigit() or len(guardian_contact) != 11):
			messages.error(request, "Guardian contact must be exactly 11 digits.")
			return redirect('violations:staff_dashboard')
		
		# Check if student ID already exists
		if StudentModel.objects.filter(student_id__iexact=student_id).exists():
			messages.error(request, f"A student with ID '{student_id}' already exists.")
			return redirect('violations:staff_dashboard')
		
		# Check if username already exists
		if User.objects.filter(username__iexact=username).exists():
			messages.error(request, f"A user with this Student ID already exists.")
			return redirect('violations:staff_dashboard')
		
		# Check if email already exists (if provided)
		if email and User.objects.filter(email__iexact=email).exists():
			messages.error(request, f"Email '{email}' is already registered.")
			return redirect('violations:staff_dashboard')
		
		try:
			# Create the user account (no password needed - student logs in via Student ID)
			user = User.objects.create_user(
				username=username,
				email=email or None,
				password=None,  # No password - student ID login
				first_name=first_name,
				last_name=f"{last_name} {suffix}".strip() if suffix else last_name,
				role=User.Role.STUDENT
			)
			
			# Create the student profile with year_level_assigned_at for auto-promotion
			StudentModel.objects.create(
				user=user,
				student_id=student_id,
				suffix=suffix,
				program=program,
				year_level=int(year_level),
				year_level_assigned_at=timezone.now(),
				department=program,  # Use program/college as department
				contact_number=contact_number or '',
				guardian_name=guardian_name or '',
				guardian_contact=guardian_contact or '',
				enrollment_status='Active'
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
		letter_suffix = request.POST.get("letter_suffix", "").strip()  # Optional
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
			existing.letter_suffix = letter_suffix
			existing.letter_home_address = letter_home_address
			existing.letter_program = letter_program
			existing.letter_violations = letter_violations
			existing.letter_printed_name = letter_printed_name
			existing.signature_data = signature_data
			existing.save()
			
			# Log activity for resubmitted apology
			from .models import ActivityLog
			ActivityLog.log_activity(
				user=request.user,
				action_type=ActivityLog.ActionType.APOLOGY_RESUBMITTED,
				description=f"Resubmitted apology letter for violation #{violation.id}",
				request=request,
				related_apology=existing,
				related_student=student,
				related_violation=violation
			)
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
				letter_suffix=letter_suffix,
				letter_home_address=letter_home_address,
				letter_program=letter_program,
				letter_violations=letter_violations,
				letter_printed_name=letter_printed_name,
				signature_data=signature_data
			)
			if apology_file:
				apology_letter.file = apology_file
			apology_letter.save()
			
			# Log activity for new apology submission
			from .models import ActivityLog
			ActivityLog.log_activity(
				user=request.user,
				action_type=ActivityLog.ActionType.APOLOGY_SUBMITTED,
				description=f"Submitted apology letter for violation #{violation.id}",
				request=request,
				related_apology=apology_letter,
				related_student=student,
				related_violation=violation
			)
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


############################################
# Staff Alert Management Views
############################################

@role_required({User.Role.STAFF})
def staff_schedule_meeting_view(request, alert_id):
	"""Staff: Schedule a meeting for a staff alert."""
	if request.method != "POST":
		return JsonResponse({"error": "Method not allowed"}, status=405)
	
	try:
		alert = StaffAlert.objects.get(id=alert_id, resolved=False)
	except StaffAlert.DoesNotExist:
		return JsonResponse({"error": "Alert not found"}, status=404)
	
	# Parse JSON data from request body
	try:
		data = json.loads(request.body)
		scheduled_meeting_str = data.get("scheduled_meeting")
		meeting_notes = data.get("meeting_notes", "")
	except json.JSONDecodeError:
		return JsonResponse({"error": "Invalid JSON data"}, status=400)
	
	if not scheduled_meeting_str:
		return JsonResponse({"error": "Meeting date/time required"}, status=400)
	
	try:
		from datetime import datetime
		# Parse datetime string from datetime-local input (format: YYYY-MM-DDTHH:MM)
		scheduled_meeting = datetime.strptime(scheduled_meeting_str, '%Y-%m-%dT%H:%M')
		alert.scheduled_meeting = scheduled_meeting
		alert.meeting_notes = meeting_notes
		alert.save()
		
		# Send notification to OSA Coordinator
		faculty_users = User.objects.filter(role=User.Role.OSA_COORDINATOR)
		for faculty in faculty_users:
			Message.objects.create(
				sender=request.user,
				receiver=faculty,
				content=f"""URGENT: Meeting Scheduled with Student

A mandatory meeting has been scheduled regarding a student who has reached the violation threshold.

Student Details:
- Student ID: {alert.student.student_id}
- Name: {alert.student.user.get_full_name() or alert.student.user.username}
- Effective Major Violations: {alert.effective_major_count}

Meeting Details:
- Date & Time: {scheduled_meeting.strftime('%B %d, %Y at %I:%M %p')}
- Location: OSA Office
- Purpose: Review violation record and determine next steps
{f"- Additional Notes: {meeting_notes}" if meeting_notes else ""}

Please be prepared to discuss the student's violation history and appropriate disciplinary actions.

This meeting was scheduled by: {request.user.get_full_name() or request.user.username}
""".strip()
			)
		
		# Send notification to the student
		Message.objects.create(
			sender=request.user,
			receiver=alert.student.user,
			content=f"""MANDATORY MEETING NOTICE

You have been scheduled for a mandatory meeting with the OSA Coordinator due to reaching the violation threshold.

Meeting Details:
- Date & Time: {scheduled_meeting.strftime('%B %d, %Y at %I:%M %p')}
- Location: OSA Office
- Purpose: Review your violation record and discuss next steps
{f"- Additional Notes: {meeting_notes}" if meeting_notes else ""}

Important Notes:
- This meeting is mandatory and your attendance is required
- Please arrive 10 minutes early
- Bring your Student ID
- Come prepared to discuss your recent violations

If you are unable to attend this scheduled time, please contact the OSA Office immediately to reschedule.

Violation Summary:
- Effective Major Violations: {alert.effective_major_count}
- Latest Violation: {alert.triggered_violation.description if alert.triggered_violation else 'N/A'}

For questions, contact the OSA Office.

Regards,
OSA Staff
{request.user.get_full_name() or request.user.username}
""".strip()
		)
		
		return JsonResponse({"status": "success", "message": "Meeting scheduled successfully. Notifications sent to student and OSA Coordinator."})
	except Exception as e:
		return JsonResponse({"error": str(e)}, status=400)


@role_required({User.Role.STAFF})
def staff_resolve_alert_view(request, alert_id):
	"""Staff: Mark a staff alert as resolved."""
	if request.method != "POST":
		return JsonResponse({"error": "Method not allowed"}, status=405)
	
	try:
		alert = StaffAlert.objects.get(id=alert_id, resolved=False)
		alert.resolved = True
		alert.resolved_at = timezone.now()
		alert.save()
		return JsonResponse({"status": "success", "message": "Alert resolved successfully"})
	except StaffAlert.DoesNotExist:
		return JsonResponse({"error": "Alert not found"}, status=404)
	except Exception as e:
		return JsonResponse({"error": str(e)}, status=400)


############################################
# Guard Portal Views
############################################

# Valid guard codes - simple authentication
VALID_GUARD_CODES = ['Guard1', 'Guard2', 'Guard3']


def guard_login_view(request):
	"""Guard login page - simple code-based authentication."""
	# Check if already logged in as guard
	if request.session.get('guard_code'):
		return redirect('violations:guard_dashboard')
	
	error = None
	guard_code = ''
	
	if request.method == 'POST':
		guard_code = request.POST.get('guard_code', '').strip()
		
		# Normalize the input (capitalize first letter of each word)
		normalized_code = guard_code.title()
		
		if normalized_code in VALID_GUARD_CODES:
			# Set session for guard
			request.session['guard_code'] = normalized_code
			request.session['guard_login_time'] = timezone.now().isoformat()
			return redirect('violations:guard_dashboard')
		else:
			error = 'Invalid guard code. Please enter a valid code (Guard1, Guard2, or Guard3).'
	
	return render(request, 'violations/guard/login.html', {
		'error': error,
		'guard_code': guard_code,
		'current_year': timezone.now().year,
	})


def guard_logout_view(request):
	"""Guard logout - clear session."""
	if 'guard_code' in request.session:
		del request.session['guard_code']
	if 'guard_login_time' in request.session:
		del request.session['guard_login_time']
	return redirect('violations:guard_login')


def guard_required(view_func):
	"""Decorator to ensure guard is logged in via session."""
	def wrapper(request, *args, **kwargs):
		if not request.session.get('guard_code'):
			return redirect('violations:guard_login')
		return view_func(request, *args, **kwargs)
	return wrapper


@guard_required
def guard_dashboard_view(request):
	"""Guard dashboard - view-only access to student info and violations."""
	guard_code = request.session.get('guard_code', 'Guard')
	
	# Get statistics for this specific guard
	total_students = StudentModel.objects.count()
	
	# Count violations reported by this specific guard
	my_reports = Violation.objects.filter(reported_by_guard=guard_code)
	my_reports_count = my_reports.count()
	
	# Today's incidents reported by this guard
	today = timezone.now().date()
	today_incidents = Violation.objects.filter(
		reported_by_guard=guard_code,
		created_at__date=today
	).count()
	
	# Pending reports (not yet resolved) for this guard
	pending_reports = Violation.objects.filter(
		reported_by_guard=guard_code,
		status__in=[Violation.Status.REPORTED, Violation.Status.UNDER_REVIEW]
	).count()
	
	# Incident reports issued by this guard (last 10)
	my_incident_reports = Violation.objects.filter(
		reported_by_guard=guard_code
	).select_related(
		'student', 'student__user', 'violation_type'
	).order_by('-created_at')[:10]
	
	# Full activity log - all violations reported by this guard
	activity_log = Violation.objects.filter(
		reported_by_guard=guard_code
	).select_related(
		'student', 'student__user', 'violation_type'
	).order_by('-created_at')[:50]
	
	activity_log_count = my_reports_count  # Total count of all reports
	
	# Count resolved reports
	resolved_reports = Violation.objects.filter(
		reported_by_guard=guard_code,
		status=Violation.Status.RESOLVED
	).count()
	
	# Student lookup
	search_id = request.GET.get('student_id', '').strip()
	searched_student = None
	
	if search_id:
		searched_student = StudentModel.objects.select_related('user').filter(
			student_id__iexact=search_id
		).first()
		
		if searched_student:
			# Add violation count
			searched_student.violation_count = Violation.objects.filter(
				student=searched_student
			).count()
	
	# Get all violation types for the incident report form
	violation_types = ViolationType.objects.all().order_by('category', 'name')
	
	ctx = {
		'guard_code': guard_code,
		'current_date': timezone.now().strftime('%B %d, %Y'),
		'total_students': total_students,
		'my_reports_count': my_reports_count,
		'today_incidents': today_incidents,
		'pending_reports': pending_reports,
		'my_incident_reports': my_incident_reports,
		'activity_log': activity_log,
		'activity_log_count': activity_log_count,
		'resolved_reports': resolved_reports,
		'search_id': search_id,
		'searched_student': searched_student,
		'violation_types': violation_types,
	}
	
	return render(request, 'violations/guard/dashboard.html', ctx)


@guard_required
def guard_report_incident_view(request):
	"""Guard can report an incident/violation they caught."""
	guard_code = request.session.get('guard_code', 'Guard')
	
	if request.method == 'POST':
		try:
			student_id = request.POST.get('student_id', '').strip()
			violation_type_id = request.POST.get('violation_type', '')
			severity = request.POST.get('severity', 'minor')
			location = request.POST.get('location', '').strip()
			description = request.POST.get('description', '').strip()
			proof_image = request.POST.get('proof_image', '')  # Base64 image data
			
			# Additional fields for new student registration
			first_name = request.POST.get('first_name', '').strip()
			last_name = request.POST.get('last_name', '').strip()
			suffix = request.POST.get('suffix', '').strip()
			email = request.POST.get('email', '').strip()
			contact_number = request.POST.get('contact_number', '').strip()
			program = request.POST.get('program', '').strip()
			year_level = request.POST.get('year_level', '1')
			guardian_name = request.POST.get('guardian_name', '').strip()
			guardian_contact = request.POST.get('guardian_contact', '').strip()
			
			# Validate student ID is 8 digits
			if not student_id.isdigit() or len(student_id) != 8:
				return JsonResponse({
					'success': False,
					'error': 'Student ID must be exactly 8 digits.'
				})
			
			# Check if student exists by student_id
			student = StudentModel.objects.filter(student_id__iexact=student_id).first()
			student_created = False
			
			if not student:
				# Validate required fields for new student
				if not first_name or not last_name:
					return JsonResponse({
						'success': False,
						'error': 'Student not found. Please provide First Name and Last Name to register.',
						'student_not_found': True
					})
				
				# Validate contact numbers are 11 digits if provided
				if contact_number and (not contact_number.isdigit() or len(contact_number) != 11):
					return JsonResponse({
						'success': False,
						'error': 'Contact number must be exactly 11 digits.'
					})
				
				if guardian_contact and (not guardian_contact.isdigit() or len(guardian_contact) != 11):
					return JsonResponse({
						'success': False,
						'error': 'Guardian contact must be exactly 11 digits.'
					})
				
				# Create a User account for the new student
				from django.contrib.auth import get_user_model
				from django.db import transaction, IntegrityError
				User = get_user_model()
				
				# Generate a username based on student_id
				username = student_id.replace('-', '').lower()
				
				# Generate email for the student
				base_email = email or f"{username}@student.chmsu.edu.ph"
				
				# Use transaction to prevent race conditions
				try:
					with transaction.atomic():
						# Double-check student doesn't exist (race condition protection)
						student = StudentModel.objects.filter(student_id__iexact=student_id).first()
						if student:
							# Student was created between our checks - use it
							pass
						else:
							# Check if user already exists with this username OR email
							existing_user = User.objects.filter(username=username).first()
							if not existing_user and email:
								# Also check by email if provided
								existing_user = User.objects.filter(email__iexact=email).first()
							
							if existing_user:
								# Check if a Student profile already exists for this user
								existing_student = StudentModel.objects.filter(user=existing_user).first()
								if existing_student:
									# Use existing student profile
									student = existing_student
								else:
									# User exists but no student profile - create one
									try:
										year_level_int = int(year_level)
									except (ValueError, TypeError):
										year_level_int = 1
									
									student = StudentModel.objects.create(
										user=existing_user,
										student_id=student_id,
										suffix=suffix,
										program=program,
										year_level=year_level_int,
										year_level_assigned_at=timezone.now(),
										department=program,
										contact_number=contact_number,
										guardian_name=guardian_name,
										guardian_contact=guardian_contact,
										enrollment_status='Active'
									)
									student_created = True
							else:
								# Create new user and student profile
								full_last_name = f"{last_name} {suffix}".strip() if suffix else last_name
								
								# Generate unique email if not provided or if it exists
								final_email = base_email
								email_counter = 1
								while User.objects.filter(email__iexact=final_email).exists():
									name_part = base_email.split('@')[0]
									domain_part = base_email.split('@')[1]
									final_email = f"{name_part}{email_counter}@{domain_part}"
									email_counter += 1
								
								# Also ensure username is unique
								final_username = username
								username_counter = 1
								while User.objects.filter(username=final_username).exists():
									final_username = f"{username}_{username_counter}"
									username_counter += 1
								
								user = User.objects.create_user(
									username=final_username,
									first_name=first_name,
									last_name=full_last_name,
									password=student_id,  # Default password is student ID
									email=final_email,
									role='student'  # Set the role to student
								)
								
								# NOTE: A signal in signals.py auto-creates a Student profile
								# when a User with role='student' is created. We need to fetch
								# and update that profile instead of creating a new one.
								try:
									year_level_int = int(year_level)
								except (ValueError, TypeError):
									year_level_int = 1
								
								# Get the auto-created student profile and update it
								student = StudentModel.objects.filter(user=user).first()
								if student:
									# Update the auto-created profile with proper data
									student.student_id = student_id
									student.suffix = suffix
									student.program = program
									student.year_level = year_level_int
									student.year_level_assigned_at = timezone.now()
									student.department = program
									student.contact_number = contact_number
									student.guardian_name = guardian_name
									student.guardian_contact = guardian_contact
									student.enrollment_status = 'Active'
									student.save()
								else:
									# Signal didn't create one, create manually
									student = StudentModel.objects.create(
										user=user,
										student_id=student_id,
										suffix=suffix,
										program=program,
										year_level=year_level_int,
										year_level_assigned_at=timezone.now(),
										department=program,
										contact_number=contact_number,
										guardian_name=guardian_name,
										guardian_contact=guardian_contact,
										enrollment_status='Active'
									)
								student_created = True
				except IntegrityError as e:
					# If we still get an integrity error, try to fetch the existing student
					student = StudentModel.objects.filter(student_id__iexact=student_id).first()
					if not student:
						# Try to find by username
						existing_user = User.objects.filter(username=username).first()
						if not existing_user and email:
							existing_user = User.objects.filter(email__iexact=email).first()
						if existing_user:
							student = StudentModel.objects.filter(user=existing_user).first()
					
					if not student:
						import traceback
						print(f"IntegrityError in guard report: {e}")
						print(traceback.format_exc())
						return JsonResponse({
							'success': False,
							'error': f'Database error: {str(e)}. The student may already exist with different details.'
						})
			
			# Get violation type if provided
			violation_type = None
			if violation_type_id:
				try:
					violation_type = ViolationType.objects.get(id=violation_type_id)
					# Use the category from the violation type as severity
					severity = violation_type.category
				except ViolationType.DoesNotExist:
					pass
			
			# Create the violation/incident report
			violation = Violation.objects.create(
				student=student,
				reported_by_guard=guard_code,
				violation_type=violation_type,
				incident_at=timezone.now(),
				type=severity,
				location=location,
				description=description,
				status=Violation.Status.REPORTED,
			)
			
			# Save proof image if provided
			if proof_image and proof_image.startswith('data:image'):
				import base64
				from django.core.files.base import ContentFile
				
				# Extract the base64 data
				format_data, imgstr = proof_image.split(';base64,')
				ext = format_data.split('/')[-1]
				
				# Create file from base64
				image_data = base64.b64decode(imgstr)
				file_name = f"proof_{violation.id}_{timezone.now().strftime('%Y%m%d_%H%M%S')}.{ext}"
				violation.evidence_file.save(file_name, ContentFile(image_data), save=True)
			
			# Build success message
			if student_created:
				message = f'Incident report #{violation.id} submitted! New student "{first_name} {last_name}" ({student_id}) was automatically registered.'
			else:
				message = f'Incident report #{violation.id} submitted successfully for {student.user.get_full_name() or student_id}!'
			
			# Log the guard activity
			from .models import ActivityLog
			student_name = student.user.get_full_name() or student_id
			ActivityLog.log_activity(
				action_type=ActivityLog.ActionType.INCIDENT_REPORTED,
				description=f"Reported incident for {student_name}: {description[:100]}..." if len(description) > 100 else f"Reported incident for {student_name}: {description}",
				request=request,
				guard_code=guard_code,
				related_student=student,
				related_violation=violation,
				attached_image=violation.evidence_file if violation.evidence_file else None
			)
			
			return JsonResponse({
				'success': True,
				'message': message,
				'violation_id': violation.id,
				'student_created': student_created,
			})
		except Exception as e:
			import traceback
			print(f"Error in guard_report_incident_view: {e}")
			print(traceback.format_exc())
			return JsonResponse({
				'success': False,
				'error': f'Server error: {str(e)}'
			})
	
	# GET request - check student existence or return violation types
	check_student_id = request.GET.get('check_student', '').strip()
	if check_student_id:
		# AJAX call to check if student exists
		student = StudentModel.objects.filter(student_id__iexact=check_student_id).first()
		if student:
			return JsonResponse({
				'exists': True,
				'student_name': student.user.get_full_name() or student.student_id,
				'program': student.program,
				'year_level': student.year_level,
			})
		else:
			return JsonResponse({'exists': False})
	
	violation_types = list(ViolationType.objects.values('id', 'name', 'severity', 'category'))
	return JsonResponse({'violation_types': violation_types})


############################################
# Student Formator Portal
############################################

VALID_FORMATOR_CODES = ['FormatorHead']


def formator_login_view(request):
	"""Formator login - code-based authentication (no password)."""
	error = None
	formator_code = ''
	
	if request.method == 'POST':
		formator_code = request.POST.get('formator_code', '').strip()
		
		# Check if valid formator code (case-insensitive match)
		normalized_code = formator_code.title().replace(' ', '')
		
		# Check against valid codes
		if normalized_code in VALID_FORMATOR_CODES or formator_code.lower() == 'formatorhead':
			# Set session for formator
			request.session['formator_code'] = 'FormatorHead'
			request.session['formator_login_time'] = timezone.now().isoformat()
			return redirect('violations:formator_dashboard')
		else:
			error = 'Invalid formator code. Please enter a valid code.'
	
	return render(request, 'violations/formator/login.html', {
		'error': error,
		'formator_code': formator_code,
		'current_year': timezone.now().year,
	})


def formator_logout_view(request):
	"""Formator logout - clear session."""
	if 'formator_code' in request.session:
		del request.session['formator_code']
	if 'formator_login_time' in request.session:
		del request.session['formator_login_time']
	return redirect('violations:formator_login')


def formator_required(view_func):
	"""Decorator to ensure formator is logged in via session."""
	def wrapper(request, *args, **kwargs):
		if not request.session.get('formator_code'):
			return redirect('violations:formator_login')
		return view_func(request, *args, **kwargs)
	return wrapper


@formator_required
def formator_dashboard_view(request):
	"""Formator dashboard - view student info, violations, and alerts."""
	formator_code = request.session.get('formator_code', 'Formator')
	
	# Get statistics
	total_students = StudentModel.objects.count()
	active_violations = Violation.objects.filter(
		status__in=[Violation.Status.REPORTED, Violation.Status.UNDER_REVIEW]
	).count()
	
	# Pending apology letters (general count)
	from .models import ApologyLetter
	pending_apologies = ApologyLetter.objects.filter(status='pending').count()
	
	# Letters pending formator review
	pending_formator_letters = ApologyLetter.objects.filter(
		formator_status='pending'
	).select_related('student', 'student__user', 'violation').order_by('-sent_to_formator_at')
	
	# Signed letters log (documents formator has signed)
	signed_letters = ApologyLetter.objects.filter(
		formator_status='signed'
	).select_related('student', 'student__user', 'violation').order_by('-formator_signed_at')[:20]
	
	# Rejected letters log
	rejected_letters = ApologyLetter.objects.filter(
		formator_status='rejected'
	).select_related('student', 'student__user', 'violation').order_by('-formator_signed_at')[:10]
	
	# Active alerts
	active_alerts = StaffAlert.objects.filter(resolved=False).count()
	
	# Recent violations (last 10)
	recent_violations = Violation.objects.select_related(
		'student', 'student__user', 'violation_type'
	).order_by('-created_at')[:10]
	
	# Students with violations (sorted by count, top 10)
	students_with_violations = StudentModel.objects.annotate(
		violation_count=Count('violations')
	).filter(violation_count__gt=0).order_by('-violation_count')[:10]
	
	# Student lookup
	search_id = request.GET.get('student_id', '').strip()
	searched_student = None
	
	if search_id:
		searched_student = StudentModel.objects.select_related('user').filter(
			student_id__iexact=search_id
		).first()
		
		if searched_student:
			# Add violation count
			searched_student.violation_count = Violation.objects.filter(
				student=searched_student
			).count()
	
	ctx = {
		'formator_code': formator_code,
		'current_date': timezone.now().strftime('%B %d, %Y'),
		'total_students': total_students,
		'active_violations': active_violations,
		'pending_apologies': pending_apologies,
		'pending_formator_letters': pending_formator_letters,
		'pending_formator_count': pending_formator_letters.count(),
		'signed_letters': signed_letters,
		'signed_letters_count': signed_letters.count(),
		'rejected_letters': rejected_letters,
		'active_alerts': active_alerts,
		'recent_violations': recent_violations,
		'students_with_violations': students_with_violations,
		'search_id': search_id,
		'searched_student': searched_student,
	}
	
	return render(request, 'violations/formator/dashboard.html', ctx)


@formator_required
def formator_verify_letter_view(request, letter_id):
	"""Formator: Review and sign an apology letter."""
	letter = get_object_or_404(
		ApologyLetter.objects.select_related('student', 'student__user', 'violation'),
		id=letter_id,
		formator_status='pending'
	)
	
	if request.method == 'POST':
		action = request.POST.get('action', '')
		formator_remarks = request.POST.get('formator_remarks', '').strip()
		formator_signature = request.POST.get('formator_signature', '')
		community_service = request.POST.get('community_service_completed') == 'on'
		
		if action == 'sign':
			letter.formator_status = 'signed'
			letter.formator_signed_at = timezone.now()
			letter.formator_signature = formator_signature
			letter.formator_remarks = formator_remarks
			letter.community_service_completed = community_service
			
			# Handle photo upload
			if 'formator_photo' in request.FILES:
				letter.formator_photo = request.FILES['formator_photo']
			
			letter.save()
			
			# Log formator activity
			from .models import ActivityLog
			formator_code = request.session.get('formator_code', 'Formator')
			student_name = letter.student.user.get_full_name() or letter.student.student_id
			ActivityLog.log_activity(
				action_type=ActivityLog.ActionType.LETTER_SIGNED,
				description=f"Signed apology letter from {student_name} for violation #{letter.violation.id}",
				request=request,
				formator_code=formator_code,
				related_apology=letter,
				related_student=letter.student,
				related_violation=letter.violation,
				attached_image=letter.formator_photo if letter.formator_photo else None
			)
			
			messages.success(request, 'Letter has been signed successfully. Staff will be notified.')
			return redirect('violations:formator_dashboard')
		
		elif action == 'reject':
			letter.formator_status = 'rejected'
			letter.formator_remarks = formator_remarks
			letter.save()
			
			# Log formator rejection activity
			from .models import ActivityLog
			formator_code = request.session.get('formator_code', 'Formator')
			student_name = letter.student.user.get_full_name() or letter.student.student_id
			ActivityLog.log_activity(
				action_type=ActivityLog.ActionType.LETTER_REJECTED_FORMATOR,
				description=f"Rejected apology letter from {student_name}. Remarks: {formator_remarks}",
				request=request,
				formator_code=formator_code,
				related_apology=letter,
				related_student=letter.student,
				related_violation=letter.violation
			)
			
			messages.warning(request, 'Letter has been rejected.')
			return redirect('violations:formator_dashboard')
	
	ctx = {
		'letter': letter,
		'formator_code': request.session.get('formator_code', 'Formator'),
	}
	return render(request, 'violations/formator/verify_letter.html', ctx)