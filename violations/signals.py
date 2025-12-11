from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.utils import timezone

from .models import User, Student, OSACoordinator, Staff, LoginActivity


@receiver(post_save, sender=User)
def create_role_profile(sender, instance: User, created: bool, **kwargs):
    if not created:
        return
    # Auto-create a matching role profile for convenience
    if instance.role == User.Role.STUDENT:
        Student.objects.create(user=instance, student_id=f"{instance.username}")
    elif instance.role == User.Role.OSA_COORDINATOR:
        OSACoordinator.objects.create(user=instance, employee_id=f"OSA-{instance.username}")
    elif instance.role == User.Role.STAFF:
        Staff.objects.create(user=instance, employee_id=f"STA-{instance.username}")
    # Record account creation event
    try:
        LoginActivity.objects.create(
            user=instance,
            event_type=LoginActivity.EventType.ACCOUNT_CREATED,
            timestamp=getattr(instance, "date_joined", None) or timezone.now(),
            ip_address="",
            user_agent="",
        )
    except Exception:
        pass


def _get_ip_address(request):
    if not request:
        return ""
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def _get_user_agent(request):
    if not request:
        return ""
    return request.META.get("HTTP_USER_AGENT", "")[:512]


@receiver(user_logged_in)
def on_user_logged_in(sender, request, user, **kwargs):  # pragma: no cover - side-effect only
    try:
        LoginActivity.objects.create(
            user=user,
            event_type=LoginActivity.EventType.LOGIN,
            timestamp=timezone.now(),
            ip_address=_get_ip_address(request),
            user_agent=_get_user_agent(request),
        )
    except Exception:
        pass


@receiver(user_logged_out)
def on_user_logged_out(sender, request, user, **kwargs):  # pragma: no cover - side-effect only
    if not user:
        return
    try:
        LoginActivity.objects.create(
            user=user,
            event_type=LoginActivity.EventType.LOGOUT,
            timestamp=timezone.now(),
            ip_address=_get_ip_address(request),
            user_agent=_get_user_agent(request),
        )
    except Exception:
        pass
