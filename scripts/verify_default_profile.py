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
from django.conf import settings
import boto3

def verify_default_profile():
    try:
        # Create S3 client
        s3 = boto3.client(
            's3',
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_S3_REGION_NAME
        )
        
        # Check if default profile picture exists in S3
        default_path = 'media/profile_pics/castolo.png'
        try:
            s3.head_object(Bucket=settings.AWS_STORAGE_BUCKET_NAME, Key=default_path)
            print(f"Default profile picture exists at s3://{settings.AWS_STORAGE_BUCKET_NAME}/{default_path}")
            return True
        except:
            print(f"Default profile picture not found in S3, attempting to upload...")
            
            # Look for the file locally
            local_paths = [
                os.path.join(settings.BASE_DIR, 'media', 'profile_pics', 'castolo.png'),
                os.path.join(settings.BASE_DIR, 'static', 'img', 'castolo.png'),
                os.path.join('/var/www/lpc/media/profile_pics', 'castolo.png'),
            ]
            
            for local_path in local_paths:
                if os.path.exists(local_path):
                    print(f"Found local file at: {local_path}")
                    # Upload to S3
                    with open(local_path, 'rb') as f:
                        s3.upload_fileobj(
                            f,
                            settings.AWS_STORAGE_BUCKET_NAME,
                            default_path,
                            ExtraArgs={'ACL': 'public-read', 'ContentType': 'image/png'}
                        )
                    print(f"Successfully uploaded default profile picture to S3")
                    return True
            
            print("ERROR: Could not find castolo.png in any of the expected locations!")
            return False
            
    except Exception as e:
        print(f"Error verifying/uploading default profile picture: {str(e)}")
        return False

if __name__ == '__main__':
    verify_default_profile() 