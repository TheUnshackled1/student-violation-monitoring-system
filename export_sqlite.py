#!/usr/bin/env python
"""Script to export SQLite data to JSON with proper UTF-8 encoding."""
import os
import sys
import json

# Set UTF-8 encoding
os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'student_violation_system.settings')

import django
django.setup()

from django.core import serializers
from django.apps import apps

def export_data():
    """Export all model data to JSON."""
    all_objects = []
    
    # Get all models
    excluded_apps = ['contenttypes', 'auth.permission']
    
    for app_config in apps.get_app_configs():
        for model in app_config.get_models():
            model_name = f"{app_config.label}.{model.__name__}"
            
            # Skip excluded
            if app_config.label == 'contenttypes':
                continue
            if model_name.lower() == 'auth.permission':
                continue
                
            try:
                queryset = model.objects.all()
                if queryset.exists():
                    print(f"Exporting {model_name}: {queryset.count()} records")
                    data = serializers.serialize('python', queryset)
                    all_objects.extend(data)
            except Exception as e:
                print(f"Error exporting {model_name}: {e}")
    
    # Write to JSON file with UTF-8 encoding
    output_file = 'sqlite_backup.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_objects, f, indent=2, ensure_ascii=False, default=str)
    
    print(f"\n✓ Exported {len(all_objects)} objects to {output_file}")

if __name__ == '__main__':
    export_data()
