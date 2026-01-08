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

	# ============================================
	# Certificate of Good Moral Character (CGMC)
	# Rule-based eligibility system per CHMSU handbook
	# ============================================

	@property
	def has_pending_case(self):
		"""Check if student has any ongoing/pending disciplinary case."""
		from .models import Violation
		return self.violations.filter(
			status__in=[Violation.Status.REPORTED, Violation.Status.UNDER_REVIEW]
		).exists()

	@property
	def pending_case_count(self):
		"""Count of pending/under review cases."""
		from .models import Violation
		return self.violations.filter(
			status__in=[Violation.Status.REPORTED, Violation.Status.UNDER_REVIEW]
		).count()

	@property
	def has_disqualifying_offense(self):
		"""Check if student has major offense punishable by suspension or higher.
		
		Disqualifying offenses include:
		- Any major violation on record (regardless of status)
		- Major violations are considered disqualifying per handbook
		"""
		return self.major_violation_count > 0

	@property
	def disqualifying_offense_count(self):
		"""Count of major offenses that disqualify from CGMC."""
		return self.major_violation_count

	@property
	def resolved_violations_count(self):
		"""Count of violations that have been resolved."""
		from .models import Violation
		return self.violations.filter(status=Violation.Status.RESOLVED).count()

	@property
	def sanctions_completed(self):
		"""Check if all violations have been resolved/addressed.
		
		Returns True if no pending cases and all past violations are resolved/dismissed.
		"""
		from .models import Violation
		total = self.violations.count()
		resolved_or_dismissed = self.violations.filter(
			status__in=[Violation.Status.RESOLVED, Violation.Status.DISMISSED]
		).count()
		return total == 0 or total == resolved_or_dismissed

	@property
	def last_violation_date(self):
		"""Get the date of the most recent violation."""
		latest = self.violations.order_by('-incident_at').first()
		return latest.incident_at if latest else None

	@property
	def clearance_period_passed(self):
		"""Check if sufficient clearance period has passed since last violation.
		
		Clearance period: 6 months (one semester) since last violation incident.
		"""
		from django.utils import timezone
		from datetime import timedelta
		
		last_date = self.last_violation_date
		if not last_date:
			return True  # No violations, clearance not needed
		
		clearance_days = 180  # ~6 months (one semester)
		return timezone.now() >= last_date + timedelta(days=clearance_days)

	@property
	def has_repeated_misconduct(self):
		"""Check for pattern of repeated violations indicating failure of moral restoration.
		
		Repeated misconduct pattern:
		- 3+ minor violations of same type, OR
		- 2+ major violations, OR  
		- Violations spanning multiple semesters with no improvement
		"""
		from .models import Violation
		
		# Check for 2+ major violations
		if self.major_violation_count >= 2:
			return True
		
		# Check for 3+ effective major violations
		if self.effective_major_violations >= 3:
			return True
		
		return False

	@property
	def cgmc_eligibility(self):
		"""Determine Certificate of Good Moral Character eligibility.
		
		Based on CHMSU Student Handbook rules:
		
		ELIGIBLE (✅): 
		- No major offense on record
		- No ongoing/pending cases
		- Minor offenses (if any) are resolved
		- No active disciplinary sanction
		
		CONDITIONALLY ELIGIBLE (⚠️):
		- Minor offenses only
		- Sanctions completed
		- Clearance period passed (1 semester)
		- May be issued with administrative discretion
		
		NOT ELIGIBLE (❌):
		- Any major offense punishable by suspension or higher
		- Unresolved/pending case
		- Pattern of repeated violations
		- 3+ effective major violations
		
		Returns dict with:
		- status: 'eligible', 'conditional', 'pending_review', 'not_eligible'
		- can_issue: Boolean
		- label: Display label
		- description: Detailed explanation
		- reasons: List of reasons affecting eligibility
		- recommendations: Actions needed (if any)
		"""
		from .models import Violation
		
		reasons = []
		recommendations = []
		
		total_violations = self.violations.count()
		major_count = self.major_violation_count
		minor_count = self.minor_violation_count
		effective_major = self.effective_major_violations
		pending_count = self.pending_case_count
		has_pending = self.has_pending_case
		sanctions_done = self.sanctions_completed
		clearance_ok = self.clearance_period_passed
		repeated_pattern = self.has_repeated_misconduct
		
		# ============================================
		# NOT ELIGIBLE (❌) - Automatic Disqualification
		# ============================================
		
		# Check for disqualifying major offense
		if major_count > 0:
			reasons.append(f"{major_count} major offense(s) on record")
			recommendations.append("Major offenses permanently affect CGMC eligibility")
			return {
				'status': 'not_eligible',
				'can_issue': False,
				'label': 'Not Eligible',
				'description': f'Student has {major_count} major disciplinary offense(s) on record, which disqualifies them from receiving a Certificate of Good Moral Character per CHMSU Student Handbook.',
				'reasons': reasons,
				'recommendations': recommendations,
				'badge_class': 'badge-ineligible',
				'icon': 'fas fa-ban',
			}
		
		# Check for pattern of repeated misconduct (3+ effective major)
		if repeated_pattern:
			reasons.append("Pattern of repeated misconduct detected")
			recommendations.append("Demonstrate sustained behavioral improvement")
			return {
				'status': 'not_eligible',
				'can_issue': False,
				'label': 'Not Eligible',
				'description': f'Student has {effective_major} effective major violations (3 minor = 1 major), indicating a pattern of misconduct that disqualifies them from CGMC.',
				'reasons': reasons,
				'recommendations': recommendations,
				'badge_class': 'badge-ineligible',
				'icon': 'fas fa-ban',
			}
		
		# ============================================
		# PENDING REVIEW - Cannot issue yet
		# ============================================
		
		if has_pending:
			reasons.append(f"{pending_count} pending/under review case(s)")
			recommendations.append("Wait for all cases to be resolved before applying for CGMC")
			return {
				'status': 'pending_review',
				'can_issue': False,
				'label': 'Pending Case Resolution',
				'description': f'Student has {pending_count} case(s) currently under investigation or pending resolution. CGMC cannot be issued until all cases are resolved.',
				'reasons': reasons,
				'recommendations': recommendations,
				'badge_class': 'badge-pending',
				'icon': 'fas fa-hourglass-half',
			}
		
		# ============================================
		# CONDITIONALLY ELIGIBLE (⚠️)
		# ============================================
		
		# Has minor violations but all resolved
		if minor_count > 0 and sanctions_done:
			if not clearance_ok:
				reasons.append(f"{minor_count} minor violation(s) - sanctions completed")
				reasons.append("Clearance period not yet passed (6 months)")
				recommendations.append("Wait for clearance period to complete")
				recommendations.append("Maintain clean disciplinary record")
				return {
					'status': 'conditional',
					'can_issue': True,  # Can issue with remarks
					'label': 'Conditionally Eligible',
					'description': f'Student has {minor_count} minor violation(s) with completed sanctions. May be issued with administrative discretion. Clearance period (6 months since last incident) has not fully passed.',
					'reasons': reasons,
					'recommendations': recommendations,
					'badge_class': 'badge-conditional',
					'icon': 'fas fa-exclamation-triangle',
				}
			else:
				reasons.append(f"{minor_count} minor violation(s) - fully resolved")
				reasons.append("Clearance period passed")
				return {
					'status': 'conditional',
					'can_issue': True,
					'label': 'Conditionally Eligible',
					'description': f'Student has {minor_count} minor violation(s) on record, but all sanctions have been completed and clearance period has passed. May be issued at administrative discretion.',
					'reasons': reasons,
					'recommendations': [],
					'badge_class': 'badge-conditional',
					'icon': 'fas fa-check-circle',
				}
		
		# ============================================
		# AUTOMATICALLY ELIGIBLE (✅)
		# ============================================
		
		if total_violations == 0:
			return {
				'status': 'eligible',
				'can_issue': True,
				'label': 'Eligible',
				'description': 'Student has no disciplinary violations on record. Eligible for Certificate of Good Moral Character.',
				'reasons': ['No disciplinary record'],
				'recommendations': [],
				'badge_class': 'badge-eligible',
				'icon': 'fas fa-medal',
			}
		
		# Default case - should not normally reach here
		return {
			'status': 'eligible',
			'can_issue': True,
			'label': 'Eligible',
			'description': 'Student meets all requirements for Certificate of Good Moral Character.',
			'reasons': ['Disciplinary record within acceptable limits'],
			'recommendations': [],
			'badge_class': 'badge-eligible',
			'icon': 'fas fa-award',
		}

	@property
	def good_moral_status(self):
		"""Simplified good moral status for backward compatibility.
		
		Returns a tuple of (status_code, status_label, status_description)
		"""
		cgmc = self.cgmc_eligibility
		return (cgmc['status'], cgmc['label'], cgmc['description'])


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
	class MeetingStatus(models.TextChoices):
		NOT_SCHEDULED = "not_scheduled", "Not Scheduled"
		SCHEDULED = "scheduled", "Scheduled"
		MET = "met", "Met/Completed"
		EXPIRED = "expired", "Did Not Meet/Expired"

	student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="alerts")
	triggered_violation = models.ForeignKey("Violation", on_delete=models.SET_NULL, null=True, blank=True)
	effective_major_count = models.PositiveIntegerField()
	created_at = models.DateTimeField(auto_now_add=True)
	resolved = models.BooleanField(default=False)
	resolved_at = models.DateTimeField(null=True, blank=True)
	scheduled_meeting = models.DateTimeField(null=True, blank=True, help_text="Scheduled meeting time with OSA Coordinator")
	meeting_notes = models.TextField(blank=True, help_text="Additional notes for the meeting")
	meeting_status = models.CharField(
		max_length=20, 
		choices=MeetingStatus.choices, 
		default=MeetingStatus.NOT_SCHEDULED,
		help_text="Current status of the scheduled meeting"
	)
	meeting_status_updated_at = models.DateTimeField(null=True, blank=True, help_text="When the meeting status was last updated")
	# Soft delete field for trash functionality
	dismissed_at = models.DateTimeField(null=True, blank=True, help_text="When the alert was dismissed/deleted")
	dismissed_by = models.ForeignKey(
		settings.AUTH_USER_MODEL, 
		on_delete=models.SET_NULL, 
		null=True, 
		blank=True, 
		related_name="dismissed_alerts",
		help_text="User who dismissed this alert"
	)

	class Meta:
		ordering = ["-created_at"]

	def mark_resolved(self):
		self.resolved = True
		self.resolved_at = timezone.now()
		self.save(update_fields=["resolved", "resolved_at"])

	def dismiss(self, user=None):
		"""Soft delete the alert by marking it as dismissed."""
		self.dismissed_at = timezone.now()
		self.dismissed_by = user
		self.save(update_fields=["dismissed_at", "dismissed_by"])

	def restore(self):
		"""Restore a dismissed alert."""
		self.dismissed_at = None
		self.dismissed_by = None
		self.save(update_fields=["dismissed_at", "dismissed_by"])

	def update_meeting_status(self, status):
		"""Update meeting status and timestamp."""
		self.meeting_status = status
		self.meeting_status_updated_at = timezone.now()
		self.save(update_fields=["meeting_status", "meeting_status_updated_at"])

	def check_meeting_expired(self):
		"""Check if meeting has expired and update status if so."""
		if (self.meeting_status == self.MeetingStatus.SCHEDULED and 
			self.scheduled_meeting and 
			self.scheduled_meeting < timezone.now()):
			self.update_meeting_status(self.MeetingStatus.EXPIRED)
			return True
		return False

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


class ActivityLog(models.Model):
	"""Track all user activities across the system for OSA Coordinator monitoring."""
	
	class ActionType(models.TextChoices):
		# Staff actions
		VIOLATION_CREATED = "violation_created", "Created Violation"
		VIOLATION_UPDATED = "violation_updated", "Updated Violation"
		VIOLATION_VERIFIED = "violation_verified", "Verified Violation"
		VIOLATION_DISMISSED = "violation_dismissed", "Dismissed Violation"
		APOLOGY_REVIEWED = "apology_reviewed", "Reviewed Apology Letter"
		APOLOGY_APPROVED = "apology_approved", "Approved Apology Letter"
		APOLOGY_REJECTED = "apology_rejected", "Rejected Apology Letter"
		APOLOGY_REVISION = "apology_revision", "Requested Apology Revision"
		APOLOGY_SENT_FORMATOR = "apology_sent_formator", "Sent to Formator"
		MESSAGE_SENT = "message_sent", "Sent Message"
		STUDENT_ADDED = "student_added", "Added Student"
		MEETING_SCHEDULED = "meeting_scheduled", "Scheduled Meeting"
		ALERT_RESOLVED = "alert_resolved", "Resolved Alert"
		
		# Student actions
		APOLOGY_SUBMITTED = "apology_submitted", "Submitted Apology Letter"
		APOLOGY_RESUBMITTED = "apology_resubmitted", "Resubmitted Apology Letter"
		PROFILE_UPDATED = "profile_updated", "Updated Profile"
		
		# Guard actions
		INCIDENT_REPORTED = "incident_reported", "Reported Incident"
		ID_CONFISCATED = "id_confiscated", "Confiscated ID"
		
		# Formator actions
		LETTER_SIGNED = "letter_signed", "Signed Apology Letter"
		LETTER_REJECTED_FORMATOR = "letter_rejected_formator", "Rejected by Formator"
		
		# OSA Coordinator actions
		VIOLATION_REPORTED = "violation_reported", "Reported Violation"
		REPORT_VIEWED = "report_viewed", "Viewed Reports"

	user = models.ForeignKey(
		settings.AUTH_USER_MODEL, 
		on_delete=models.CASCADE, 
		related_name="activity_logs",
		null=True,
		blank=True,
		help_text="User who performed the action (null for guards/formators using code-based login)"
	)
	guard_code = models.CharField(
		max_length=50, 
		blank=True, 
		help_text="Guard code for guard activities"
	)
	formator_code = models.CharField(
		max_length=50, 
		blank=True, 
		help_text="Formator code for formator activities"
	)
	action_type = models.CharField(max_length=50, choices=ActionType.choices)
	description = models.TextField(help_text="Detailed description of the activity")
	
	# Related objects (optional - for linking to specific records)
	related_violation = models.ForeignKey(
		'Violation', 
		on_delete=models.SET_NULL, 
		null=True, 
		blank=True, 
		related_name="activity_logs"
	)
	related_student = models.ForeignKey(
		'Student', 
		on_delete=models.SET_NULL, 
		null=True, 
		blank=True, 
		related_name="activity_logs"
	)
	related_apology = models.ForeignKey(
		'ApologyLetter', 
		on_delete=models.SET_NULL, 
		null=True, 
		blank=True, 
		related_name="activity_logs"
	)
	
	# Attached image/evidence
	attached_image = models.ImageField(
		upload_to="activity_logs/%Y/%m/", 
		blank=True, 
		null=True,
		help_text="Optional image attachment for the activity"
	)
	
	# Metadata
	ip_address = models.CharField(max_length=45, blank=True)
	user_agent = models.TextField(blank=True)
	timestamp = models.DateTimeField(auto_now_add=True)
	
	class Meta:
		ordering = ["-timestamp"]
		verbose_name = "Activity Log"
		verbose_name_plural = "Activity Logs"
	
	def __str__(self):
		if self.user:
			actor = self.user.username
		elif self.guard_code:
			actor = f"Guard: {self.guard_code}"
		elif self.formator_code:
			actor = f"Formator: {self.formator_code}"
		else:
			actor = "Unknown"
		return f"{actor} - {self.get_action_type_display()} at {self.timestamp:%Y-%m-%d %H:%M}"
	
	def get_actor_display(self):
		"""Return a display name for the actor who performed the activity."""
		if self.user:
			return self.user.get_full_name() or self.user.username
		elif self.guard_code:
			return f"Guard: {self.guard_code}"
		elif self.formator_code:
			return f"Formator: {self.formator_code}"
		return "Unknown"
	
	def get_actor_role(self):
		"""Return the role of the actor."""
		if self.user:
			return self.user.get_role_display() if hasattr(self.user, 'get_role_display') else self.user.role
		elif self.guard_code:
			return "Guard"
		elif self.formator_code:
			return "Formator"
		return "Unknown"
	
	@classmethod
	def log_activity(cls, action_type, description, request=None, user=None, guard_code=None, formator_code=None, **kwargs):
		"""Helper method to create activity log entries.
		
		Args:
			action_type: The type of action being logged
			description: Detailed description of the activity
			request: HTTP request object (optional, for IP/user agent)
			user: User object for staff/student/coordinator activities
			guard_code: Guard code for guard activities
			formator_code: Formator code for formator activities
			**kwargs: Additional fields (related_violation, related_student, etc.)
		"""
		ip_address = ""
		user_agent = ""
		if request:
			x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
			if x_forwarded_for:
				ip_address = x_forwarded_for.split(',')[0].strip()
			else:
				ip_address = request.META.get('REMOTE_ADDR', '')
			user_agent = request.META.get('HTTP_USER_AGENT', '')
		
		return cls.objects.create(
			user=user,
			guard_code=guard_code or '',
			formator_code=formator_code or '',
			action_type=action_type,
			description=description,
			ip_address=ip_address,
			user_agent=user_agent,
			**kwargs
		)


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
	letter_suffix = models.CharField(max_length=20, blank=True, help_text="Name suffix (Jr., Sr., III, etc.) - Optional")
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

