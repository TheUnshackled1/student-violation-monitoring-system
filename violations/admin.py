from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.utils.html import format_html

from .models import (
	User,
	Student,
	OSACoordinator,
	Staff,
	Message,
	Violation,
	ViolationType,
	ViolationDocument,
	ApologyLetter,
	StaffVerification,
	LoginActivity,
	ChatMessage,
)


# =============================================================================
# Custom Admin Site Configuration
# =============================================================================
admin.site.site_header = "CHMSU Student Violation System"
admin.site.site_title = "CHMSU Violations Admin"
admin.site.index_title = "Welcome to CHMSU Student Violation Management"


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
	list_display = ("username", "email", "first_name", "last_name", "role_badge", "is_active", "last_login")
	list_filter = ("role", "is_active", "is_staff", "is_superuser")
	search_fields = ("username", "email", "first_name", "last_name")
	readonly_fields = ("created_at",)
	list_per_page = 25
	
	fieldsets = (
		(None, {"fields": ("username", "password")}),
		("Personal Info", {"fields": ("first_name", "last_name", "email", "role", "created_at")}),
		(
			"Permissions",
			{
				"fields": (
					"is_active",
					"is_staff",
					"is_superuser",
					"groups",
					"user_permissions",
				),
				"classes": ("collapse",),
			},
		),
		("Important Dates", {"fields": ("last_login", "date_joined"), "classes": ("collapse",)}),
	)
	
	@admin.display(description="Role")
	def role_badge(self, obj):
		colors = {
			"student": "#22c55e",
			"staff": "#3b82f6",
			"osa_coordinator": "#f59e0b",
		}
		color = colors.get(obj.role, "#6b7280")
		return format_html(
			'<span style="background-color:{}; color:white; padding:3px 10px; border-radius:12px; font-size:11px; font-weight:600;">{}</span>',
			color, obj.get_role_display()
		)


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
	list_display = ("student_id", "get_full_name", "program", "year_level", "department_badge", "enrollment_badge")
	search_fields = ("student_id", "user__username", "user__first_name", "user__last_name", "program")
	list_filter = ("enrollment_status", "department", "year_level", "program")
	list_per_page = 25
	ordering = ("student_id",)
	
	fieldsets = (
		("Student Information", {
			"fields": ("user", "student_id", "program", "year_level", "department")
		}),
		("Contact Information", {
			"fields": ("contact_number", "guardian_name", "guardian_contact"),
			"classes": ("collapse",),
		}),
		("Status & Media", {
			"fields": ("enrollment_status", "profile_image"),
		}),
	)
	
	@admin.display(description="Name", ordering="user__first_name")
	def get_full_name(self, obj):
		return obj.user.get_full_name() or obj.user.username
	
	@admin.display(description="Department")
	def department_badge(self, obj):
		# Official CHMSU College/Department Colors
		colors = {
			"CAS": "#22c55e",      # Green - College of Arts and Sciences
			"CBMA": "#eab308",     # Yellow/Gold - College of Business Management and Accountancy
			"CCS": "#6b7280",      # Gray - College of Computer Studies
			"COEd": "#3b82f6",     # Blue - College of Education
			"CIT": "#ef4444",      # Red - College of Industrial Technology
			"COE": "#f97316",      # Orange - College of Engineering
			"CON": "#ec4899",      # Pink - College of Nursing
			"CTHM": "#8b5cf6",     # Purple - College of Tourism and Hospitality Management
			"CAF": "#14b8a6",      # Teal - College of Agriculture and Fishery
			"CGS": "#1a472a",      # Dark Green - College of Graduate Studies
		}
		dept = obj.department or "—"
		color = colors.get(dept, "#64748b")  # Slate gray for unknown
		return format_html(
			'<span style="background-color:{}; color:white; padding:3px 10px; border-radius:12px; font-size:11px; font-weight:600;">{}</span>',
			color, dept
		)
	
	@admin.display(description="Status")
	def enrollment_badge(self, obj):
		colors = {
			"Enrolled": "#22c55e",
			"Suspended": "#ef4444",
			"Graduated": "#3b82f6",
			"Dropped": "#6b7280",
		}
		status = obj.enrollment_status or "Unknown"
		color = colors.get(status, "#6b7280")
		return format_html(
			'<span style="background-color:{}; color:white; padding:3px 10px; border-radius:12px; font-size:11px;">{}</span>',
			color, status
		)


@admin.register(OSACoordinator)
class OSACoordinatorAdmin(admin.ModelAdmin):
	list_display = ("employee_id", "get_full_name", "position", "office_location")
	search_fields = ("employee_id", "user__username", "user__first_name", "user__last_name")
	list_per_page = 25
	
	@admin.display(description="Name", ordering="user__first_name")
	def get_full_name(self, obj):
		return obj.user.get_full_name() or obj.user.username


@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
	list_display = ("employee_id", "get_full_name", "department", "position", "office_location")
	search_fields = ("employee_id", "user__username", "user__first_name", "user__last_name")
	list_filter = ("department",)
	list_per_page = 25
	
	@admin.display(description="Name", ordering="user__first_name")
	def get_full_name(self, obj):
		return obj.user.get_full_name() or obj.user.username


@admin.register(ViolationType)
class ViolationTypeAdmin(admin.ModelAdmin):
	list_display = ("display_name_formatted", "category_badge", "code", "is_active_badge", "created_at")
	list_filter = ("category", "is_active")
	search_fields = ("name", "code", "description")
	list_per_page = 25
	ordering = ("category", "name")
	list_editable = ("code",)
	
	fieldsets = (
		("Violation Information", {
			"fields": ("name", "category", "code", "is_active")
		}),
		("Details", {
			"fields": ("description", "penalty"),
			"classes": ("collapse",),
		}),
	)
	
	@admin.display(description="Violation")
	def display_name_formatted(self, obj):
		prefix = "MO" if obj.category == "major" else "MiO"
		prefix_color = "#ef4444" if obj.category == "major" else "#f59e0b"
		return format_html(
			'<span style="color:{}; font-weight:600;">{}</span>: {}',
			prefix_color, prefix, obj.name
		)
	
	@admin.display(description="Category")
	def category_badge(self, obj):
		colors = {"minor": "#f59e0b", "major": "#ef4444"}
		labels = {"minor": "Minor Offense", "major": "Major Offense"}
		color = colors.get(obj.category, "#6b7280")
		label = labels.get(obj.category, obj.category)
		return format_html(
			'<span style="background-color:{}; color:white; padding:3px 10px; border-radius:12px; font-size:11px; font-weight:600;">{}</span>',
			color, label
		)
	
	@admin.display(description="Status")
	def is_active_badge(self, obj):
		if obj.is_active:
			return format_html(
				'<span style="background-color:#22c55e; color:white; padding:3px 10px; border-radius:12px; font-size:11px;">Active</span>'
			)
		return format_html(
			'<span style="background-color:#6b7280; color:white; padding:3px 10px; border-radius:12px; font-size:11px;">Inactive</span>'
		)


@admin.register(Violation)
class ViolationAdmin(admin.ModelAdmin):
	list_display = ("id", "get_student_name", "type_badge", "status_badge", "incident_at", "reported_by", "created_at")
	list_filter = ("type", "status", "incident_at", "created_at")
	search_fields = ("student__student_id", "student__user__username", "student__user__first_name", "location", "description")
	list_per_page = 25
	date_hierarchy = "incident_at"
	ordering = ("-created_at",)
	
	fieldsets = (
		("Violation Details", {
			"fields": ("student", "type", "status", "description")
		}),
		("Incident Information", {
			"fields": ("incident_at", "location"),
		}),
		("Documentation", {
			"fields": ("reported_by",),
			"classes": ("collapse",),
		}),
	)
	
	@admin.display(description="Student")
	def get_student_name(self, obj):
		if obj.student:
			return f"{obj.student.user.get_full_name()} ({obj.student.student_id})"
		return "—"
	
	@admin.display(description="Type")
	def type_badge(self, obj):
		colors = {"minor": "#f59e0b", "major": "#ef4444"}
		color = colors.get(obj.type, "#6b7280")
		return format_html(
			'<span style="background-color:{}; color:white; padding:3px 10px; border-radius:12px; font-size:11px; font-weight:600; text-transform:uppercase;">{}</span>',
			color, obj.get_type_display()
		)
	
	@admin.display(description="Status")
	def status_badge(self, obj):
		colors = {
			"reported": "#3b82f6",
			"under_review": "#f59e0b",
			"resolved": "#22c55e",
			"dismissed": "#6b7280",
		}
		color = colors.get(obj.status, "#6b7280")
		return format_html(
			'<span style="background-color:{}; color:white; padding:3px 10px; border-radius:12px; font-size:11px;">{}</span>',
			color, obj.get_status_display()
		)


@admin.register(ViolationDocument)
class ViolationDocumentAdmin(admin.ModelAdmin):
	list_display = ("id", "violation", "document_type", "uploaded_at")
	list_filter = ("document_type", "uploaded_at")
	search_fields = ("violation__student__student_id", "description")
	list_per_page = 25


@admin.register(ApologyLetter)
class ApologyLetterAdmin(admin.ModelAdmin):
	list_display = ("id", "get_student_name", "violation", "status_badge", "submitted_at", "verified_by")
	list_filter = ("status", "submitted_at")
	search_fields = ("student__student_id", "student__user__first_name", "content")
	list_per_page = 25
	date_hierarchy = "submitted_at"
	
	@admin.display(description="Student")
	def get_student_name(self, obj):
		if obj.student:
			return f"{obj.student.user.get_full_name()} ({obj.student.student_id})"
		return "—"
	
	@admin.display(description="Status")
	def status_badge(self, obj):
		colors = {"pending": "#f59e0b", "verified": "#22c55e", "rejected": "#ef4444"}
		color = colors.get(obj.status, "#6b7280")
		return format_html(
			'<span style="background-color:{}; color:white; padding:3px 10px; border-radius:12px; font-size:11px;">{}</span>',
			color, obj.status.title()
		)


@admin.register(StaffVerification)
class StaffVerificationAdmin(admin.ModelAdmin):
	list_display = ("id", "violation", "staff", "action_badge", "notes_preview", "created_at")
	list_filter = ("action", "created_at")
	search_fields = ("violation__student__student_id", "staff__username", "notes")
	list_per_page = 25
	date_hierarchy = "created_at"
	
	@admin.display(description="Action")
	def action_badge(self, obj):
		colors = {"verified": "#22c55e", "corrected": "#3b82f6", "flagged": "#f59e0b", "approved": "#22c55e"}
		color = colors.get(obj.action, "#6b7280")
		return format_html(
			'<span style="background-color:{}; color:white; padding:3px 10px; border-radius:12px; font-size:11px;">{}</span>',
			color, obj.get_action_display()
		)
	
	@admin.display(description="Notes")
	def notes_preview(self, obj):
		if obj.notes:
			return obj.notes[:30] + "..." if len(obj.notes) > 30 else obj.notes
		return "—"


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
	list_display = ("id", "sender", "receiver", "content_preview", "created_at", "read_badge")
	search_fields = ("sender__username", "receiver__username", "content")
	list_filter = ("created_at",)
	list_per_page = 25
	date_hierarchy = "created_at"
	
	@admin.display(description="Message")
	def content_preview(self, obj):
		return obj.content[:50] + "..." if len(obj.content) > 50 else obj.content
	
	@admin.display(description="Read")
	def read_badge(self, obj):
		if obj.read_at:
			return format_html('<span style="color:#22c55e;"><i class="fas fa-check-double"></i> Read</span>')
		return format_html('<span style="color:#f59e0b;"><i class="fas fa-clock"></i> Unread</span>')


@admin.register(LoginActivity)
class LoginActivityAdmin(admin.ModelAdmin):
	list_display = ("user", "event_type", "ip_address", "timestamp")
	list_filter = ("event_type", "timestamp")
	search_fields = ("user__username", "ip_address")
	list_per_page = 50
	date_hierarchy = "timestamp"
	readonly_fields = ("user", "event_type", "ip_address", "user_agent", "timestamp")


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
	list_display = ("id", "sender", "room", "content_preview", "created_at")
	search_fields = ("sender__username", "content", "room")
	list_filter = ("room", "created_at")
	list_per_page = 50
	date_hierarchy = "created_at"
	
	@admin.display(description="Message")
	def content_preview(self, obj):
		return obj.content[:50] + "..." if len(obj.content) > 50 else obj.content
