import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'student_violation_system.settings')

import django
django.setup()

from violations.models import Violation
from django.utils import timezone
from datetime import timedelta

# Calculate threshold (7 days ago)
threshold = timezone.now() - timedelta(days=7)
print(f"Today: {timezone.now().strftime('%Y-%m-%d')}")
print(f"Overdue threshold: {threshold.strftime('%Y-%m-%d')} (cases created before this are overdue)")
print()

# Get overdue cases
overdue = Violation.objects.filter(
    status__in=['reported', 'under_review'],
    created_at__lt=threshold
)

print(f"Overdue cases count: {overdue.count()}")
print()

for v in overdue:
    print(f"  Case #{v.id}: {v.student.student_id}")
    print(f"    Status: {v.status}")
    print(f"    Created: {v.created_at.strftime('%Y-%m-%d')}")
    days_old = (timezone.now() - v.created_at).days
    print(f"    Days pending: {days_old} days")
    print()

print("---")
print("All pending cases:")
pending = Violation.objects.filter(status__in=['reported', 'under_review'])
for v in pending:
    days_old = (timezone.now() - v.created_at).days
    is_overdue = "⚠️ OVERDUE" if days_old > 7 else ""
    print(f"  Case #{v.id}: {v.student.student_id} - {v.status} - {v.created_at.strftime('%Y-%m-%d')} ({days_old} days old) {is_overdue}")
