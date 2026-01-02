"""
Management command to auto-promote students based on 10-month year level duration.

This command should be run daily via cron job or Windows Task Scheduler:
    python manage.py auto_promote_students

Students will be:
- Promoted to the next year level after 10 months at current level
- Graduated automatically after completing 4th year (10 months after reaching 4th year)
"""
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from violations.models import Student


class Command(BaseCommand):
    help = 'Auto-promote students based on 10-month year level duration'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be promoted without making changes',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        now = timezone.now()
        # 10 months = approximately 304 days (30.4 days per month average)
        promotion_threshold = timedelta(days=304)
        
        # Get active students with year_level_assigned_at set
        active_students = Student.objects.filter(
            enrollment_status='Active',
            year_level_assigned_at__isnull=False
        )
        
        promoted_count = 0
        graduated_count = 0
        
        for student in active_students:
            time_at_level = now - student.year_level_assigned_at
            
            if time_at_level >= promotion_threshold:
                if student.year_level < 4:
                    # Promote to next year level
                    old_level = student.year_level
                    new_level = old_level + 1
                    
                    if dry_run:
                        self.stdout.write(
                            f"[DRY RUN] Would promote {student.student_id} "
                            f"from Year {old_level} to Year {new_level}"
                        )
                    else:
                        student.year_level = new_level
                        student.year_level_assigned_at = now
                        student.save(update_fields=['year_level', 'year_level_assigned_at'])
                        self.stdout.write(self.style.SUCCESS(
                            f"Promoted {student.student_id} ({student.user.get_full_name()}) "
                            f"from Year {old_level} to Year {new_level}"
                        ))
                    promoted_count += 1
                    
                elif student.year_level == 4:
                    # Graduate 4th year students after 10 months
                    if dry_run:
                        self.stdout.write(
                            f"[DRY RUN] Would graduate {student.student_id}"
                        )
                    else:
                        student.enrollment_status = 'Graduated'
                        student.save(update_fields=['enrollment_status'])
                        self.stdout.write(self.style.SUCCESS(
                            f"Graduated {student.student_id} ({student.user.get_full_name()})"
                        ))
                    graduated_count += 1
        
        # Summary
        self.stdout.write('')
        if dry_run:
            self.stdout.write(self.style.WARNING(
                f"[DRY RUN] Would promote {promoted_count} students and graduate {graduated_count} students"
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Summary: Promoted {promoted_count} students, Graduated {graduated_count} students"
            ))
