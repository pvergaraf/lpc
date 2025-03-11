import boto3
import os
from botocore.exceptions import ClientError

def verify_s3():
    print("\nVerifying AWS Credentials:")
    print("-----------------------")
    for key in ['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_STORAGE_BUCKET_NAME', 'AWS_S3_REGION_NAME']:
        value = os.environ.get(key)
        print(f"{key}: {'✓ Set' if value else '✗ Missing'}")

    try:
        print("\nTesting S3 Connection:")
        print("-------------------")
        s3 = boto3.client('s3')
        
        # Test file upload
        print("Uploading test file...")
        test_content = b"Test content"
        s3.put_object(
            Bucket=os.environ['AWS_STORAGE_BUCKET_NAME'],
            Key='static/test_upload.txt',
            Body=test_content,
            ACL='public-read'
        )
        print("✓ Upload successful")
        
        # Test file download
        print("Downloading test file...")
        obj = s3.get_object(
            Bucket=os.environ['AWS_STORAGE_BUCKET_NAME'],
            Key='static/test_upload.txt'
        )
        content = obj['Body'].read()
        print("✓ Download successful")
        
        # List all files
        print("\nCurrent files in bucket:")
        print("----------------------")
        response = s3.list_objects_v2(
            Bucket=os.environ['AWS_STORAGE_BUCKET_NAME'],
            Prefix='static/'
        )
        
        if 'Contents' in response:
            for obj in response['Contents']:
                print(f"- {obj['Key']} ({obj['Size']} bytes)")
        else:
            print("No files found")
            
    except ClientError as e:
        print(f"\n✗ Error: {e}")
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")

if __name__ == "__main__":
    verify_s3()