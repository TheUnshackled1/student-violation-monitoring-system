import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'student_violation_system.settings')

import django
django.setup()

from violations.models import ApologyLetter, Violation

# Find all approved apology letters
approved = ApologyLetter.objects.filter(status='approved').select_related('violation', 'student', 'student__user')

print(f"Found {approved.count()} approved apology letters")
print()

updated = 0
for letter in approved:
    student_name = letter.student.user.get_full_name() or letter.student.student_id
    current_status = letter.violation.status
    
    if current_status != 'resolved':
        letter.violation.status = 'resolved'
        letter.violation.save()
        updated += 1
        print(f"✓ Updated: Violation #{letter.violation.id} ({student_name}): {current_status} → resolved")
    else:
        print(f"  Already resolved: Violation #{letter.violation.id} ({student_name})")

print()
print(f"Updated {updated} violations to resolved status")
print()

# Show current counts
print("Current violation counts:")
print(f"  Total: {Violation.objects.count()}")
print(f"  Reported: {Violation.objects.filter(status='reported').count()}")
print(f"  Under Review: {Violation.objects.filter(status='under_review').count()}")
print(f"  Resolved: {Violation.objects.filter(status='resolved').count()}")
print(f"  Dismissed: {Violation.objects.filter(status='dismissed').count()}")
