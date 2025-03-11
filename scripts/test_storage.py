#!/usr/bin/env python3
import os
import sys
from pathlib import Path

# Add the project root directory to the Python path
sys.path.append(str(Path(__file__).resolve().parent.parent))

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'club_project.settings')
import django
django.setup()

from django.conf import settings
from django.core.files.storage import default_storage
from django.contrib.staticfiles.storage import staticfiles_storage

def main():
    print("\nDjango Settings:")
    print("-" * 50)
    print(f"DEBUG: {settings.DEBUG}")
    print(f"STATICFILES_STORAGE: {settings.STATICFILES_STORAGE}")
    print(f"DEFAULT_FILE_STORAGE: {settings.DEFAULT_FILE_STORAGE}")
    print(f"STATIC_URL: {settings.STATIC_URL}")
    print(f"AWS_S3_CUSTOM_DOMAIN: {getattr(settings, 'AWS_S3_CUSTOM_DOMAIN', 'Not set')}")
    print(f"AWS_STORAGE_BUCKET_NAME: {getattr(settings, 'AWS_STORAGE_BUCKET_NAME', 'Not set')}")
    print(f"STATIC_ROOT: {settings.STATIC_ROOT}")
    print(f"STATICFILES_DIRS: {settings.STATICFILES_DIRS}")

    print("\nStorage Info:")
    print("-" * 50)
    print(f"staticfiles_storage class: {staticfiles_storage.__class__.__name__}")
    print(f"default_storage class: {default_storage.__class__.__name__}")

    # Test if we can list files in the static storage
    print("\nTesting Static Storage:")
    print("-" * 50)
    try:
        if hasattr(staticfiles_storage, 'bucket'):
            print("Listing files in S3 bucket:")
            bucket = staticfiles_storage.bucket
            for obj in bucket.objects.filter(Prefix='static/'):
                print(f"- {obj.key} ({obj.size} bytes)")
        else:
            print("Static storage is not using S3")
    except Exception as e:
        print(f"Error accessing static storage: {str(e)}")

if __name__ == '__main__':
    main()