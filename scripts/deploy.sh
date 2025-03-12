#!/bin/bash

# Exit on error
set -e

echo "Starting deployment..."

# Change to the application directory
cd /var/www/lpc || exit

# Reset any local changes and clean untracked files
echo "Cleaning local changes..."
git reset --hard HEAD
git clean -fd

# Pull latest changes forcefully
echo "Pulling latest changes..."
git fetch origin main
git reset --hard origin/main

# Ensure virtual environment exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Upgrade pip first
echo "Upgrading pip..."
venv/bin/pip install --upgrade pip

# Install/update dependencies
echo "Installing dependencies..."
venv/bin/pip install -r requirements.txt

# Verify python-dotenv is installed
if ! venv/bin/pip show python-dotenv > /dev/null; then
    echo "Installing python-dotenv..."
    venv/bin/pip install python-dotenv
fi

# Collect static files
echo "Collecting static files..."
venv/bin/python manage.py collectstatic --noinput

# Make migrations if needed
echo "Checking for new migrations..."
venv/bin/python manage.py makemigrations

# Apply database migrations
echo "Applying database migrations..."
venv/bin/python manage.py migrate

# Set proper permissions
echo "Setting permissions..."
sudo chown -R www-data:www-data /var/www/lpc
sudo chmod -R 755 /var/www/lpc

# Restart Gunicorn
echo "Restarting Gunicorn..."
sudo systemctl restart lpc

# Restart Nginx
echo "Restarting Nginx..."
sudo systemctl restart nginx

# Deactivate virtual environment
deactivate

echo "Deployment completed successfully!"