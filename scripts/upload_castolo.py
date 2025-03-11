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

from django.core.files.storage import default_storage
from django.core.files import File

def upload_castolo():
    # Path to the local castolo.png file
    local_path = os.path.join('media', 'profile_pics', 'castolo.png')
    s3_path = 'profile_pics/castolo.png'
    
    # Check if file exists locally
    if not os.path.exists(local_path):
        print(f"Error: {local_path} not found")
        return
    
    # Upload to S3
    with open(local_path, 'rb') as f:
        if not default_storage.exists(s3_path):
            default_storage.save(s3_path, File(f))
            print(f"Castolo profile picture uploaded to {s3_path}")
        else:
            print(f"Castolo profile picture already exists at {s3_path}")

if __name__ == '__main__':
    upload_castolo() 