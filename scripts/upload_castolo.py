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
from django.conf import settings
import boto3

def upload_castolo():
    try:
        # Create S3 client directly
        s3 = boto3.client(
            's3',
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_S3_REGION_NAME
        )
        
        # Path to the local castolo.png file
        local_path = os.path.join(settings.BASE_DIR, 'media', 'profile_pics', 'castolo.png')
        s3_path = 'profile_pics/castolo.png'
        
        # Check if file exists locally
        if not os.path.exists(local_path):
            print(f"Error: {local_path} not found")
            return
        
        # Upload to S3
        with open(local_path, 'rb') as f:
            s3.upload_fileobj(
                f,
                settings.AWS_STORAGE_BUCKET_NAME,
                s3_path,
                ExtraArgs={'ACL': 'public-read'}
            )
            print(f"Castolo profile picture uploaded to {s3_path}")
            
    except Exception as e:
        print(f"Error uploading file: {str(e)}")

if __name__ == '__main__':
    # Print debug info
    print(f"AWS Settings:")
    print(f"Bucket: {settings.AWS_STORAGE_BUCKET_NAME}")
    print(f"Region: {settings.AWS_S3_REGION_NAME}")
    print(f"Access Key: {'Set' if settings.AWS_ACCESS_KEY_ID else 'Not Set'}")
    print(f"Secret Key: {'Set' if settings.AWS_SECRET_ACCESS_KEY else 'Not Set'}")
    
    upload_castolo()