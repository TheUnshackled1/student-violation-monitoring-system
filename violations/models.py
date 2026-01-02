from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.mail import send_mail
from django.core.validators import RegexValidator


# Validator for 8-digit student ID
student_id_validator = RegexValidator(
	regex=r'^\d{8}$',
	message='Student ID must be exactly 8 digits (numbers only).'
)


class User(AbstractUser):
	class Role(models.TextChoices):
		OSA_COORDINATOR = "osa_coordinator", "OSA Coordinator"
		STAFF = "staff", "Staff"
		STUDENT = "student", "Student"

	# Keep username from AbstractUser
	# Ensure unique email (optional but matches spec)
	email = models.EmailField(max_length=100, unique=True)
	role = models.CharField(max_length=20, choices=Role.choices)
	created_at = models.DateTimeField(auto_now_add=True)
	# last_login provided by AbstractUser

	def __str__(self) -> str:  # pragma: no cover - repr only
		return f"{self.username} ({self.get_role_display()})"


class Student(models.Model):
	# College/Program choices
	class College(models.TextChoices):
		CAS = "CAS", "CAS - College of Arts and Sciences"
		CBMA = "CBMA", "CBMA - College of Business Management and Accountancy"
		CCS = "CCS", "CCS - College of Computer Studies"
		COEd = "COEd", "COEd - College of Education"
		CIT = "CIT", "CIT - College of Industrial Technology"
		COE = "COE", "COE - College of Engineering"

	user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="student_profile")
	student_id = models.CharField(
		max_length=8, 
		unique=True, 
		validators=[student_id_validator],
		help_text="8-digit student ID number (e.g., 20240001)"
	)
	suffix = models.CharField(max_length=10, blank=True, help_text="Name suffix (Jr., Sr., III, etc.)")
	program = models.CharField(max_length=100, choices=College.choices, blank=True)
	year_level = models.PositiveIntegerField(default=1)
	year_level_assigned_at = models.DateTimeField(null=True, blank=True, help_text="When the current year level was assigned (for auto-promotion)")
	department = models.CharField(max_length=100, blank=True)
	enrollment_status = models.CharField(
		max_length=10,
		choices=(
			("Active", "Active"),
			("Suspended", "Suspended"),
			("Graduated", "Graduated"),
		),
		default="Active",
	)
	contact_number = models.CharField(max_length=15, blank=True)
	guardian_name = models.CharField(max_length=100, blank=True)
	guardian_contact = models.CharField(max_length=15, blank=True)
	profile_image = models.ImageField(upload_to="profiles/students/", blank=True, null=True)

	def __str__(self) -> str:  # pragma: no cover
		return f"{self.student_id} - {self.user.get_full_name() or self.user.username}"

	@property
	def major_violation_count(self):
		"""Count of major violations for this student (type == 'major')."""
		return self.violations.filter(type="major").count()

	@property
	def minor_violation_count(self):
		"""Count of minor violations for this student (type == 'minor')."""
		return self.violations.filter(type="minor").count()

	@property
	def effective_major_violations(self):
		"""Calculate effective major violations where 3 minors == 1 major.

		Returns: int
		"""
		return self.major_violation_count + (self.minor_violation_count // 3)

	@property
	def should_alert_staff(self):
		"""True when effective major violations >= 3 (trigger staff alert)."""
		return self.effective_major_violations >= 3


class OSACoordinator(models.Model):
	"""OSA Coordinator profile (formerly Faculty)"""
	user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="osa_coordinator_profile")
	employee_id = models.CharField(max_length=20, unique=True)
	position = models.CharField(max_length=100, blank=True)
	contact_number = models.CharField(max_length=15, blank=True)
	office_location = models.CharField(max_length=100, blank=True)

	class Meta:
		verbose_name = "OSA Coordinator"
		verbose_name_plural = "OSA Coordinators"

	def __str__(self) -> str:  # pragma: no cover
		return f"{self.employee_id} - {self.user.get_full_name() or self.user.username}"


class Staff(models.Model):
	user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="staff_profile")
	employee_id = models.CharField(max_length=20, unique=True)
	department = models.CharField(max_length=100, blank=True)
	position = models.CharField(max_length=100, blank=True)
	contact_number = models.CharField(max_length=15, blank=True)
	office_location = models.CharField(max_length=100, blank=True)

	def __str__(self) -> str:  # pragma: no cover
		return f"{self.employee_id} - {self.user.get_full_name() or self.user.username}"


class TemporaryAccessRequest(models.Model):
	class Status(models.TextChoices):
		PENDING = "pending", "Pending"
		APPROVED = "approved", "Approved"
		DENIED = "denied", "Denied"

	requester = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="temp_access_requests")
	reason = models.TextField()
	duration_hours = models.PositiveIntegerField(default=1)
	status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
	approved_by = models.ForeignKey(
		settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="temp_access_approvals"
	)
	requested_at = models.DateTimeField(auto_now_add=True)
	approved_at = models.DateTimeField(null=True, blank=True)
	expires_at = models.DateTimeField(null=True, blank=True)

	def approve(self, approver: "User"):
		self.status = self.Status.APPROVED
		self.approved_by = approver
		self.approved_at = timezone.now()
		self.expires_at = self.approved_at + timezone.timedelta(hours=self.duration_hours)
		self.save(update_fields=["status", "approved_by", "approved_at", "expires_at"])

	def deny(self, approver: "User"):
		self.status = self.Status.DENIED
		self.approved_by = approver
		self.approved_at = timezone.now()
		self.save(update_fields=["status", "approved_by", "approved_at"])

	@property
	def is_active(self) -> bool:
		return self.status == self.Status.APPROVED and (self.expires_at is None or self.expires_at > timezone.now())

	def __str__(self) -> str:  # pragma: no cover
		return f"TempAccess({self.requester} → {self.status})"


class Message(models.Model):
	sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="messages_sent")
	receiver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="messages_received")
	content = models.TextField()
	created_at = models.DateTimeField(auto_now_add=True)
	read_at = models.DateTimeField(null=True, blank=True)
	# Soft delete fields - each user can delete from their view independently
	deleted_by_sender = models.DateTimeField(null=True, blank=True)
	deleted_by_receiver = models.DateTimeField(null=True, blank=True)

	class Meta:
		ordering = ["-created_at"]

	def mark_read(self):
		if not self.read_at:
			self.read_at = timezone.now()
			self.save(update_fields=["read_at"])

	def delete_for_user(self, user):
		"""Soft delete message for a specific user."""
		if user == self.sender:
			self.deleted_by_sender = timezone.now()
			self.save(update_fields=["deleted_by_sender"])
		elif user == self.receiver:
			self.deleted_by_receiver = timezone.now()
			self.save(update_fields=["deleted_by_receiver"])

	def restore_for_user(self, user):
		"""Restore soft-deleted message for a specific user."""
		if user == self.sender:
			self.deleted_by_sender = None
			self.save(update_fields=["deleted_by_sender"])
		elif user == self.receiver:
			self.deleted_by_receiver = None
			self.save(update_fields=["deleted_by_receiver"])

	def __str__(self) -> str:  # pragma: no cover
		return f"Msg from {self.sender} to {self.receiver} at {self.created_at:%Y-%m-%d %H:%M}"


class ChatMessage(models.Model):
	"""Room-based chat messages persisted for the staff↔OSA Coordinator room.

	Used by the realtime chat consumer to provide history and persistence.
	"""
	sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_messages")
	room = models.CharField(max_length=100, default="staff-osa")
	content = models.TextField()
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ["created_at"]

	def __str__(self) -> str:  # pragma: no cover
		return f"ChatMessage({self.sender.username}@{self.room} {self.created_at:%Y-%m-%d %H:%M})"


class ViolationType(models.Model):
	"""Catalog of all violation types that can be assigned to students.
	
	Allows OSA to manage violation types dynamically from the admin panel.
	"""
	class Category(models.TextChoices):
		MAJOR = "major", "Major Offense (MO)"
		MINOR = "minor", "Minor Offense (MiO)"

	name = models.CharField(max_length=255, help_text="Name/description of the violation")
	category = models.CharField(max_length=10, choices=Category.choices, default=Category.MINOR)
	code = models.CharField(max_length=20, blank=True, help_text="Optional violation code for reference")
	description = models.TextField(blank=True, help_text="Detailed description or guidelines")
	penalty = models.TextField(blank=True, help_text="Standard penalty for this violation type")
	is_active = models.BooleanField(default=True, help_text="Inactive violations won't appear in selection")
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["category", "name"]
		verbose_name = "Violation Type"
		verbose_name_plural = "Violation Types"

	def __str__(self) -> str:
		prefix = "MO" if self.category == "major" else "MiO"
		return f"{prefix}: {self.name}"

	@property
	def display_name(self):
		"""Returns formatted name with category prefix."""
		prefix = "MO" if self.category == "major" else "MiO"
		return f"{prefix}: {self.name}"


class StaffAlert(models.Model):
	"""Record alerts when a student reaches the threshold of effective major violations.

	Use this to notify staff and avoid duplicate alerts while an alert remains unresolved.
	"""
	student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="alerts")
	triggered_violation = models.ForeignKey("Violation", on_delete=models.SET_NULL, null=True, blank=True)
	effective_major_count = models.PositiveIntegerField()
	created_at = models.DateTimeField(auto_now_add=True)
	resolved = models.BooleanField(default=False)
	resolved_at = models.DateTimeField(null=True, blank=True)
	scheduled_meeting = models.DateTimeField(null=True, blank=True, help_text="Scheduled meeting time with OSA Coordinator")
	meeting_notes = models.TextField(blank=True, help_text="Additional notes for the meeting")

	class Meta:
		ordering = ["-created_at"]

	def mark_resolved(self):
		self.resolved = True
		self.resolved_at = timezone.now()
		self.save(update_fields=["resolved", "resolved_at"])

	def __str__(self):
		return f"StaffAlert({self.student.student_id} = {self.effective_major_count} @ {self.created_at:%Y-%m-%d %H:%M})"


class Violation(models.Model):
	class Severity(models.TextChoices):
		MINOR = "minor", "Minor"
		MAJOR = "major", "Major"

	class Status(models.TextChoices):
		REPORTED = "reported", "Reported"
		UNDER_REVIEW = "under_review", "Under Review"
		RESOLVED = "resolved", "Resolved"
		DISMISSED = "dismissed", "Dismissed"

	student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="violations")
	reported_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="violations_reported")
	reported_by_guard = models.CharField(
		max_length=20, 
		blank=True, 
		null=True,
		help_text="Guard code if reported by security guard (Guard1, Guard2, Guard3)"
	)
	violation_type = models.ForeignKey(
		ViolationType, 
		null=True, 
		blank=True, 
		on_delete=models.SET_NULL, 
		related_name="violations",
		help_text="Specific violation type from the catalog"
	)
	incident_at = models.DateTimeField()
	type = models.CharField(max_length=10, choices=Severity.choices)
	location = models.CharField(max_length=200)
	description = models.TextField()
	witness_statement = models.TextField(blank=True)
	evidence_file = models.FileField(upload_to="violations/evidence/", null=True, blank=True)
	status = models.CharField(max_length=20, choices=Status.choices, default=Status.REPORTED)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	@property
	def reporter(self):  # for template compatibility
		return self.reported_by

	def __str__(self) -> str:  # pragma: no cover
		return f"{self.get_type_display()} violation for {self.student} on {self.incident_at:%Y-%m-%d}"


class LoginActivity(models.Model):
	class EventType(models.TextChoices):
		ACCOUNT_CREATED = "account_created", "Account Created"
		LOGIN = "login", "Login"
		LOGOUT = "logout", "Logout"

	user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="login_activities")
	event_type = models.CharField(max_length=32, choices=EventType.choices)
	timestamp = models.DateTimeField(auto_now_add=True)
	ip_address = models.CharField(max_length=45, blank=True)  # IPv4/IPv6 max length
	user_agent = models.TextField(blank=True)

	class Meta:
		ordering = ["-timestamp"]

	def __str__(self) -> str:  # pragma: no cover
		return f"LoginActivity({self.user.username} {self.event_type} at {self.timestamp:%Y-%m-%d %H:%M:%S})"


# ============================================
# STAFF CORE FEATURE MODELS
# ============================================

class ViolationDocument(models.Model):
	"""Digital copies of evidence/documents attached to violations."""
	class DocType(models.TextChoices):
		CITATION_TICKET = "citation_ticket", "Citation Ticket"
		INCIDENT_FORM = "incident_form", "Incident Form"
		PHOTO_EVIDENCE = "photo_evidence", "Photo Evidence"
		WITNESS_STATEMENT = "witness_statement", "Witness Statement"
		OTHER = "other", "Other"

	violation = models.ForeignKey(Violation, on_delete=models.CASCADE, related_name="documents")
	document_type = models.CharField(max_length=32, choices=DocType.choices, default=DocType.OTHER)
	file = models.FileField(upload_to="violations/documents/%Y/%m/")
	description = models.CharField(max_length=255, blank=True)
	uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
	uploaded_at = models.DateTimeField(auto_now_add=True)

	def __str__(self):
		return f"{self.get_document_type_display()} for Violation #{self.violation.id}"


class ApologyLetter(models.Model):
	"""Track apology letter submissions and verification."""
	class Status(models.TextChoices):
		PENDING = "pending", "Pending Review"
		APPROVED = "approved", "Approved"
		REJECTED = "rejected", "Rejected"
		REVISION_NEEDED = "revision_needed", "Revision Needed"

	class FormatorStatus(models.TextChoices):
		NOT_SENT = "not_sent", "Not Sent to Formator"
		PENDING = "pending", "Pending Formator Review"
		SIGNED = "signed", "Signed by Formator"
		REJECTED = "rejected", "Rejected by Formator"

	violation = models.ForeignKey(Violation, on_delete=models.CASCADE, related_name="apology_letters")
	student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="apology_letters")
	file = models.FileField(upload_to="apology_letters/%Y/%m/", blank=True, null=True)
	submitted_at = models.DateTimeField(auto_now_add=True)
	status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
	verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="verified_apologies")
	verified_at = models.DateTimeField(null=True, blank=True)
	remarks = models.TextField(blank=True, help_text="Staff notes/feedback")
	
	# Letter form data fields (Step 2 - Official CHMSU Form)
	letter_date = models.CharField(max_length=100, blank=True, help_text="Date on the letter")
	letter_campus = models.CharField(max_length=200, blank=True, help_text="Campus name")
	letter_full_name = models.CharField(max_length=200, blank=True, help_text="Student full name")
	letter_home_address = models.CharField(max_length=500, blank=True, help_text="Home address")
	letter_program = models.CharField(max_length=300, blank=True, help_text="Program, Major, Year & Section")
	letter_violations = models.TextField(blank=True, help_text="Specific violation/s")
	letter_printed_name = models.CharField(max_length=200, blank=True, help_text="Printed name for signature")
	signature_data = models.TextField(blank=True, help_text="Base64 encoded signature image")

	# Formator verification workflow fields
	formator_status = models.CharField(max_length=20, choices=FormatorStatus.choices, default=FormatorStatus.NOT_SENT)
	sent_to_formator_at = models.DateTimeField(null=True, blank=True, help_text="When staff sent to formator")
	sent_to_formator_by = models.ForeignKey(
		settings.AUTH_USER_MODEL, 
		on_delete=models.SET_NULL, 
		null=True, 
		blank=True, 
		related_name="letters_sent_to_formator"
	)
	formator_signed_at = models.DateTimeField(null=True, blank=True, help_text="When formator signed")
	formator_signature = models.TextField(blank=True, help_text="Base64 encoded formator signature")
	formator_photo = models.ImageField(
		upload_to="apology_letters/formator_photos/%Y/%m/", 
		blank=True, 
		null=True,
		help_text="Photo evidence of community service completion"
	)
	formator_remarks = models.TextField(blank=True, help_text="Formator notes/comments")
	community_service_completed = models.BooleanField(default=False, help_text="Has the student completed community service")

	class Meta:
		ordering = ["-submitted_at"]

	def __str__(self):
		return f"Apology Letter from {self.student.student_id} for Violation #{self.violation.id}"


class StaffVerification(models.Model):
	"""Record staff verification actions on violations."""
	class Action(models.TextChoices):
		VERIFIED = "verified", "Verified Correct"
		CORRECTED = "corrected", "Corrected"
		FLAGGED = "flagged", "Flagged for Review"
		APPROVED = "approved", "Approved"

	violation = models.ForeignKey(Violation, on_delete=models.CASCADE, related_name="verifications")
	staff = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="staff_verifications")
	action = models.CharField(max_length=20, choices=Action.choices)
	notes = models.TextField(blank=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ["-created_at"]

	def __str__(self):
		return f"{self.get_action_display()} by {self.staff.username} on Violation #{self.violation.id}"


# Signal: create a StaffAlert when a Violation is created and the student's
# effective major violations (3 minors = 1 major) reach the alert threshold.
@receiver(post_save, sender='violations.Violation')
def violation_post_save_alert(sender, instance, created, **kwargs):
	try:
		if not created:
			return

		student = instance.student

		# Compute effective majors: majors + floor(minors / 3)
		major_count = student.violations.filter(type='major').count()
		minor_count = student.violations.filter(type='minor').count()
		effective = major_count + (minor_count // 3)

		# Threshold is 3 effective major violations
		if effective >= 3:
			# Only create an alert if there is no unresolved alert already
			unresolved_exists = student.alerts.filter(resolved=False).exists()
			if not unresolved_exists:
				alert = StaffAlert.objects.create(
					student=student,
					triggered_violation=instance,
					effective_major_count=effective,
				)
				
				# Notify all staff via email
				staff_emails = list(User.objects.filter(role=User.Role.STAFF).values_list('email', flat=True))
				if staff_emails:
					subject = f"Student Alert: {student.student_id} Reached Violation Threshold"
					message = f"""
Dear Staff,

A student has reached the violation threshold requiring immediate attention.

Student Details:
- Student ID: {student.student_id}
- Name: {student.user.get_full_name() or student.user.username}
- Effective Major Violations: {effective} (Majors: {major_count}, Minors: {minor_count})
- Latest Violation: {instance.description} (Type: {instance.get_type_display()})

Please schedule a meeting with the student and the OSA Coordinator as soon as possible.

This is an automated notification from the CHMSU Violation System.

Regards,
CHMSU Violation Monitoring System
					""".strip()
					send_mail(
						subject,
						message,
						settings.DEFAULT_FROM_EMAIL,
						staff_emails,
						fail_silently=True,
					)
	except Exception:
		# Avoid raising errors during model save; log externally if available
		pass

