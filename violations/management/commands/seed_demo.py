from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from violations.models import User, Message


class Command(BaseCommand):
    help = "Seed demo users (Faculty Admin, OSA Staff, Student) with profiles and sample data"

    def handle(self, *args, **options):
        UserModel = get_user_model()

        def ensure_user(username, email, role, password, first_name, last_name):
            user, created = UserModel.objects.get_or_create(
                username=username,
                defaults={
                    "email": email,
                    "role": role,
                    "first_name": first_name,
                    "last_name": last_name,
                    "is_active": True,
                },
            )
            if created:
                user.set_password(password)
                user.save()
                self.stdout.write(self.style.SUCCESS(f"Created user {username} ({role})"))
            else:
                self.stdout.write(f"User {username} exists")
            return user

        faculty = ensure_user(
            username="osa_coordinator",
            email="osa@chmsu.edu.ph",
            role=User.Role.OSA_COORDINATOR,
            password="Passw0rd!",
            first_name="Fiona",
            last_name="Coordinator",
        )
        staff = ensure_user(
            username="osa_staff",
            email="staff@chmsu.edu.ph",
            role=User.Role.STAFF,
            password="Passw0rd!",
            first_name="Sam",
            last_name="Staff",
        )
        student = ensure_user(
            username="student1",
            email="student1@chmsu.edu.ph",
            role=User.Role.STUDENT,
            password="Passw0rd!",
            first_name="Juan",
            last_name="Dela Cruz",
        )

        # Sample messages
        Message.objects.get_or_create(sender=faculty, receiver=staff, content="Please review report #102.")
        Message.objects.get_or_create(sender=staff, receiver=faculty, content="Acknowledged. Starting review.")

        self.stdout.write(self.style.SUCCESS("Demo data seeding complete."))
