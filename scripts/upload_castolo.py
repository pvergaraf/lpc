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

def validate_aws_settings():
    required_settings = {
        'AWS_ACCESS_KEY_ID': settings.AWS_ACCESS_KEY_ID,
        'AWS_SECRET_ACCESS_KEY': settings.AWS_SECRET_ACCESS_KEY,
        'AWS_STORAGE_BUCKET_NAME': settings.AWS_STORAGE_BUCKET_NAME,
        'AWS_S3_REGION_NAME': getattr(settings, 'AWS_S3_REGION_NAME', None)
    }
    
    missing = [k for k, v in required_settings.items() if not v]
    if missing:
        raise ValueError(f"Missing required AWS settings: {', '.join(missing)}")
    return required_settings

def upload_castolo():
    try:
        # Validate AWS settings first
        aws_settings = validate_aws_settings()
        print("\nValidating AWS settings...")
        print(f"Bucket: {aws_settings['AWS_STORAGE_BUCKET_NAME']}")
        print(f"Region: {aws_settings['AWS_S3_REGION_NAME']}")
        print(f"Access Key: {'Set' if aws_settings['AWS_ACCESS_KEY_ID'] else 'Not Set'}")
        print(f"Secret Key: {'Set' if aws_settings['AWS_SECRET_ACCESS_KEY'] else 'Not Set'}\n")
        
        # Create S3 client directly
        s3 = boto3.client(
            's3',
            aws_access_key_id=aws_settings['AWS_ACCESS_KEY_ID'],
            aws_secret_access_key=aws_settings['AWS_SECRET_ACCESS_KEY'],
            region_name=aws_settings['AWS_S3_REGION_NAME']
        )
        
        # Path to the local castolo.png file
        local_path = os.path.join(settings.BASE_DIR, 'media', 'profile_pics', 'castolo.png')
        s3_path = 'profile_pics/castolo.png'
        
        print(f"Checking for local file at: {local_path}")
        
        # Check if file exists locally
        if not os.path.exists(local_path):
            print(f"Error: Local file not found at {local_path}")
            print("Checking if file exists in current directory...")
            
            # Try current directory as fallback
            current_dir_path = os.path.join(os.getcwd(), 'media', 'profile_pics', 'castolo.png')
            if os.path.exists(current_dir_path):
                print(f"Found file in current directory at {current_dir_path}")
                local_path = current_dir_path
            else:
                raise FileNotFoundError(f"Could not find castolo.png in either {local_path} or {current_dir_path}")
        
        print(f"Found local file. Uploading to S3 at {s3_path}...")
        
        # Upload to S3 without ACL
        with open(local_path, 'rb') as f:
            s3.upload_fileobj(
                f,
                aws_settings['AWS_STORAGE_BUCKET_NAME'],
                s3_path
            )
            print(f"Successfully uploaded castolo profile picture to s3://{aws_settings['AWS_STORAGE_BUCKET_NAME']}/{s3_path}")
            
    except Exception as e:
        print(f"\nError uploading file:")
        print(f"Type: {type(e).__name__}")
        print(f"Message: {str(e)}")
        print("\nStack trace:")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    upload_castolo()