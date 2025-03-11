#!/bin/bash

# Navigate to the project directory
cd /var/www/lpc

# Exit on error
set -e

echo "Starting deployment..."

echo "Discarding local changes..."
git checkout -- .

echo "Pulling latest changes..."
git pull origin main

echo "Installing dependencies..."
# Install dependencies as www-data user with proper virtual environment
sudo -u www-data bash -c 'source /var/www/lpc/venv/bin/activate && pip install -r /var/www/lpc/requirements.txt'

echo "Setting correct permissions..."
# Set ownership
sudo chown -R www-data:www-data /var/www/lpc
# Set directory permissions
sudo find /var/www/lpc -type d -exec chmod 2775 {} \;
# Set file permissions
sudo find /var/www/lpc -type f -exec chmod 664 {} \;
# Set specific permissions for sensitive files
sudo chmod 660 /var/www/lpc/.env.production
sudo chmod 660 /var/www/lpc/django.log
# Make scripts executable
sudo chmod +x /var/www/lpc/scripts/*
sudo chmod +x /var/www/lpc/venv/bin/*

echo "Collecting static files..."
# Load environment variables and run collectstatic as www-data, properly handling special characters
sudo -u www-data bash -c '
    while IFS="=" read -r key value; do
        # Skip comments and empty lines
        [[ $key =~ ^#.*$ ]] && continue
        [[ -z $key ]] && continue
        # Remove any leading/trailing whitespace
        key=$(echo $key | xargs)
        value=$(echo $value | xargs)
        # Export the variable
        export "$key=$value"
    done < /var/www/lpc/.env.production
    source /var/www/lpc/venv/bin/activate
    echo "AWS Environment Check:"
    echo "AWS_STORAGE_BUCKET_NAME: $AWS_STORAGE_BUCKET_NAME"
    echo "AWS_S3_REGION_NAME: $AWS_S3_REGION_NAME"
    echo "AWS_ACCESS_KEY_ID is set: $(if [ -n "$AWS_ACCESS_KEY_ID" ]; then echo "yes"; else echo "no"; fi)"
    echo "AWS_SECRET_ACCESS_KEY is set: $(if [ -n "$AWS_SECRET_ACCESS_KEY" ]; then echo "yes"; else echo "no"; fi)"
    python /var/www/lpc/manage.py collectstatic --no-input --clear
'

echo "Restarting application..."
sudo systemctl restart lpc
sudo systemctl restart nginx

echo "Showing application status..."
sudo systemctl status lpc
sudo systemctl status nginx

echo "Deployment completed!"