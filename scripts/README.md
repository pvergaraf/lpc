# Maintenance Scripts

This directory contains various maintenance scripts for the LPC application.

## Available Scripts

- `deploy.sh`: Deploys the latest changes and restarts the application
- `test_s3.py`: Tests AWS S3 connectivity and lists bucket contents
- `test_s3_with_env.sh`: Wrapper script to run test_s3.py with environment variables
- `collect_static.sh`: Collects and uploads static files to S3

## Usage

First time setup on the server:
```bash
# Create environment file
sudo nano /var/www/lpc/.env.production

# Add required environment variables:
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
AWS_STORAGE_BUCKET_NAME=your_bucket
AWS_S3_REGION_NAME=your_region
DJANGO_SETTINGS_MODULE=club_project.settings
DEBUG=False

# Set permissions
sudo chmod 600 /var/www/lpc/.env.production
sudo chown www-data:www-data /var/www/lpc/.env.production
```

Running the scripts:
```bash
# Deploy changes
sudo /var/www/lpc/scripts/deploy.sh

# Test S3 connection
sudo -u www-data /var/www/lpc/scripts/test_s3_with_env.sh

# Collect static files
sudo -u www-data /var/www/lpc/scripts/collect_static.sh
```
```

After accepting these files:
1. Make sure they're in the `scripts` directory
2. Commit and push your changes
3. SSH into your server
4. Run `cd /var/www/lpc && sudo chmod +x scripts/deploy.sh && sudo scripts/deploy.sh`

Let me know if you need any adjustments to the files!