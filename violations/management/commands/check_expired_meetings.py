"""
Management command to check for expired meetings and send notifications.

This command should be run periodically (e.g., via cron job) to:
1. Check all scheduled meetings that have passed
2. Mark them as expired if the student didn't meet
3. Send notifications to both student and OSA Coordinator
4. Log the activity

Usage:
    python manage.py check_expired_meetings

Recommended cron schedule (every 15 minutes):
    */15 * * * * cd /path/to/project && python manage.py check_expired_meetings
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings
from django.core.mail import send_mail

from violations.models import StaffAlert, Message, User


class Command(BaseCommand):
    help = 'Check for expired meetings and send notifications to students and OSA Coordinator'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making changes',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed output',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        verbose = options['verbose']
        
        now = timezone.now()
        expired_count = 0
        notified_count = 0
        
        # Find all scheduled meetings that have passed
        expired_meetings = StaffAlert.objects.filter(
            resolved=False,
            meeting_status=StaffAlert.MeetingStatus.SCHEDULED,
            scheduled_meeting__lt=now
        ).select_related('student', 'student__user', 'triggered_violation')
        
        if verbose or dry_run:
            self.stdout.write(f"Found {expired_meetings.count()} expired meetings to process")
        
        for alert in expired_meetings:
            student = alert.student
            meeting_time = alert.scheduled_meeting
            
            if verbose:
                self.stdout.write(f"  - Processing alert #{alert.id} for {student.student_id}")
            
            if dry_run:
                self.stdout.write(f"    [DRY-RUN] Would mark as expired and notify")
                expired_count += 1
                continue
            
            # Update status to expired
            alert.meeting_status = StaffAlert.MeetingStatus.EXPIRED
            alert.meeting_status_updated_at = now
            alert.save(update_fields=['meeting_status', 'meeting_status_updated_at'])
            expired_count += 1
            
            # Get a staff user to send notifications from
            system_user = User.objects.filter(role=User.Role.STAFF).first()
            if not system_user:
                system_user = User.objects.filter(role=User.Role.OSA_COORDINATOR).first()
            
            if system_user:
                # Send notification to the student
                Message.objects.create(
                    sender=system_user,
                    receiver=student.user,
                    content=f"""⚠️ MEETING MISSED - URGENT NOTICE

Your mandatory meeting with the OSA Coordinator has EXPIRED because you did not attend.

Meeting Details:
- Scheduled Time: {meeting_time.strftime('%B %d, %Y at %I:%M %p')}
- Location: OSA Office
- Status: DID NOT MEET / EXPIRED

⚠️ IMPORTANT:
This is a serious matter. You were required to attend this meeting due to reaching the violation threshold ({alert.effective_major_count} effective major violations).

Next Steps:
1. Contact the OSA Office IMMEDIATELY to reschedule
2. Failure to comply may result in additional disciplinary action
3. Your violation record will reflect this missed meeting

For questions or to reschedule, contact the OSA Office as soon as possible.

This is an automated notification from the CHMSU Violation Monitoring System.
""".strip()
                )
                notified_count += 1
                
                # Send notification to all OSA Coordinators
                osa_users = User.objects.filter(role=User.Role.OSA_COORDINATOR)
                for osa in osa_users:
                    Message.objects.create(
                        sender=system_user,
                        receiver=osa,
                        content=f"""⚠️ MEETING MISSED ALERT

A student has FAILED to attend their scheduled meeting.

Student Details:
- Student ID: {student.student_id}
- Name: {student.user.get_full_name() or student.user.username}
- Effective Major Violations: {alert.effective_major_count}

Meeting Details:
- Scheduled Time: {meeting_time.strftime('%B %d, %Y at %I:%M %p')}
- Location: OSA Office
- Status: DID NOT MEET / EXPIRED

Recommended Action:
- Consider rescheduling the meeting
- Review student's violation history
- May require additional disciplinary measures

The student has been notified about the missed meeting.

This is an automated notification from the CHMSU Violation Monitoring System.
""".strip()
                    )
                
                # Also send notification to all Staff
                staff_users = User.objects.filter(role=User.Role.STAFF)
                for staff in staff_users:
                    if staff != system_user:  # Don't notify ourselves
                        Message.objects.create(
                            sender=system_user,
                            receiver=staff,
                            content=f"""⚠️ MEETING MISSED ALERT

A student has FAILED to attend their scheduled meeting.

Student Details:
- Student ID: {student.student_id}
- Name: {student.user.get_full_name() or student.user.username}

Meeting Details:
- Scheduled Time: {meeting_time.strftime('%B %d, %Y at %I:%M %p')}
- Status: DID NOT MEET / EXPIRED

Please follow up on this alert and consider rescheduling the meeting.

This is an automated notification.
""".strip()
                        )
            
            if verbose:
                self.stdout.write(self.style.SUCCESS(f"    Marked as expired and sent notifications"))
        
        # Summary
        if dry_run:
            self.stdout.write(self.style.WARNING(
                f"\n[DRY-RUN] Would have processed {expired_count} expired meetings"
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"\nProcessed {expired_count} expired meetings, sent {notified_count} notifications"
            ))
