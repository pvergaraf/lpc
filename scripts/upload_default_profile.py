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
from PIL import Image
import io

def create_default_profile_picture():
    # Create a simple default profile picture
    size = (300, 300)
    color = (200, 200, 200)  # Light gray
    
    image = Image.new('RGB', size, color)
    
    # Save the image to a bytes buffer
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    buffer.seek(0)
    
    # Upload to S3
    default_path = 'profile_pics/default.png'
    if not default_storage.exists(default_path):
        default_storage.save(default_path, File(buffer))
        print(f"Default profile picture uploaded to {default_path}")
    else:
        print(f"Default profile picture already exists at {default_path}")

if __name__ == '__main__':
    create_default_profile_picture() 