import boto3
import os
from botocore.exceptions import ClientError

def test_s3():
    print("AWS Environment Variables:")
    print(f"AWS_ACCESS_KEY_ID exists: {bool(os.environ.get('AWS_ACCESS_KEY_ID'))}")
    print(f"AWS_SECRET_ACCESS_KEY exists: {bool(os.environ.get('AWS_SECRET_ACCESS_KEY'))}")
    print(f"AWS_STORAGE_BUCKET_NAME: {os.environ.get('AWS_STORAGE_BUCKET_NAME')}")
    print(f"AWS_S3_REGION_NAME: {os.environ.get('AWS_S3_REGION_NAME')}")

    try:
        s3 = boto3.client('s3')
        print("\nTrying to list bucket contents...")
        response = s3.list_objects_v2(
            Bucket=os.environ.get('AWS_STORAGE_BUCKET_NAME'),
            Prefix='static/'
        )
        print("List operation successful!")
        if 'Contents' in response:
            print("\nFiles in static/:")
            for obj in response['Contents']:
                print(f"- {obj['Key']}")
        else:
            print("No files found in static/")
            
    except ClientError as e:
        print(f"\nError: {str(e)}")
    except Exception as e:
        print(f"\nUnexpected error: {str(e)}")

if __name__ == "__main__":
    test_s3()