# Custom migration to rename Faculty to OSACoordinator
# Generated for Student Violation Monitoring System

from django.db import migrations, models


def update_role_values_forward(apps, schema_editor):
    """Update existing 'faculty_admin' role values to 'osa_coordinator'."""
    User = apps.get_model('violations', 'User')
    User.objects.filter(role='faculty_admin').update(role='osa_coordinator')


def update_role_values_backward(apps, schema_editor):
    """Revert 'osa_coordinator' role values to 'faculty_admin'."""
    User = apps.get_model('violations', 'User')
    User.objects.filter(role='osa_coordinator').update(role='faculty_admin')


class Migration(migrations.Migration):

    dependencies = [
        ("violations", "0007_message_deleted_by_receiver_and_more"),
    ]

    operations = [
        # Step 1: Rename the table from violations_faculty to violations_osacoordinator
        migrations.RenameModel(
            old_name='Faculty',
            new_name='OSACoordinator',
        ),
        
        # Step 2: Update the related_name on the user field
        migrations.AlterField(
            model_name='osacoordinator',
            name='user',
            field=models.OneToOneField(
                on_delete=models.CASCADE,
                related_name='osa_coordinator_profile',
                to='violations.user',
            ),
        ),
        
        # Step 3: Add verbose names
        migrations.AlterModelOptions(
            name='osacoordinator',
            options={
                'verbose_name': 'OSA Coordinator',
                'verbose_name_plural': 'OSA Coordinators',
            },
        ),
        
        # Step 4: Update the role field choices
        migrations.AlterField(
            model_name='user',
            name='role',
            field=models.CharField(
                choices=[
                    ('osa_coordinator', 'OSA Coordinator'),
                    ('staff', 'Staff'),
                    ('student', 'Student'),
                ],
                max_length=20,
            ),
        ),
        
        # Step 5: Run data migration to update existing role values
        migrations.RunPython(
            update_role_values_forward,
            update_role_values_backward,
        ),
    ]
