from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
	class Role(models.TextChoices):
		FACULTY_ADMIN = "faculty_admin", "Faculty(Admin)"
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
	user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="student_profile")
	student_id = models.CharField(max_length=20, unique=True)
	program = models.CharField(max_length=100, blank=True)
	year_level = models.PositiveIntegerField(default=1)
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


class Faculty(models.Model):
	user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="faculty_profile")
	employee_id = models.CharField(max_length=20, unique=True)
	position = models.CharField(max_length=100, blank=True)
	contact_number = models.CharField(max_length=15, blank=True)
	office_location = models.CharField(max_length=100, blank=True)

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

	class Meta:
		ordering = ["-created_at"]

	def mark_read(self):
		if not self.read_at:
			self.read_at = timezone.now()
			self.save(update_fields=["read_at"])

	def __str__(self) -> str:  # pragma: no cover
		return f"Msg from {self.sender} to {self.receiver} at {self.created_at:%Y-%m-%d %H:%M}"


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

