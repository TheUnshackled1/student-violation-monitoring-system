#!/usr/bin/env python
"""Script to import JSON data to PostgreSQL with proper handling."""
import os
import sys
import json

# Set UTF-8 encoding
os.environ['PYTHONIOENCODING'] = 'utf-8'

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'student_violation_system.settings')

import django
django.setup()

from django.core import serializers
from django.db import connection
from django.apps import apps

def reset_sequences():
    """Reset PostgreSQL sequences after data import."""
    with connection.cursor() as cursor:
        # Get all tables
        cursor.execute("""
            SELECT tablename FROM pg_tables 
            WHERE schemaname = 'public'
        """)
        tables = cursor.fetchall()
        
        for (table,) in tables:
            try:
                # Reset sequence if it exists
                cursor.execute(f"""
                    SELECT setval(pg_get_serial_sequence('{table}', 'id'), 
                           COALESCE((SELECT MAX(id) FROM "{table}"), 1), 
                           true)
                """)
            except Exception:
                pass  # Table might not have id column

def import_data():
    """Import JSON data to PostgreSQL."""
    input_file = 'sqlite_backup.json'
    
    print(f"Reading {input_file}...")
    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    print(f"Found {len(data)} objects to import")
    
    # Disable signals during import
    from django.db.models.signals import post_save, pre_save
    from violations.signals import create_role_profile
    from violations.models import User
    
    # Disconnect the signal that creates Student profiles automatically
    post_save.disconnect(create_role_profile, sender=User)
    
    # Convert back to JSON string for deserializer
    json_data = json.dumps(data, ensure_ascii=False)
    
    # Import without transaction to continue on errors
    objects = list(serializers.deserialize('json', json_data))
    
    success_count = 0
    error_count = 0
    
    for obj in objects:
        try:
            obj.save()
            success_count += 1
        except Exception as e:
            error_count += 1
            model_name = obj.object.__class__.__name__
            print(f"Error [{model_name}]: {e}")
    
    # Reconnect signal
    post_save.connect(create_role_profile, sender=User)
    
    # Reset sequences
    print("\nResetting PostgreSQL sequences...")
    reset_sequences()
    
    print(f"\n✓ Successfully imported {success_count} objects")
    print(f"✗ Failed to import {error_count} objects")

if __name__ == '__main__':
    import_data()
