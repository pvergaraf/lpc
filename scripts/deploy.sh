#!/bin/bash

# Navigate to the project directory
cd /var/www/lpc

# Discard any local changes
echo "Discarding local changes..."
git reset --hard HEAD
git clean -fd

# Pull the latest changes
echo "Pulling latest changes..."
git pull

# Install any new dependencies
echo "Installing dependencies..."
source venv/bin/activate
pip install -r requirements.txt

# Collect static files
echo "Collecting static files..."
source .env.production
python manage.py collectstatic --no-input

# Set script permissions
echo "Setting script permissions..."
sudo chmod +x scripts/*.sh
sudo chown www-data:www-data scripts/*

# Restart the application
echo "Restarting application..."
sudo systemctl restart lpc
sudo systemctl restart nginx

# Show status
echo "Showing application status..."
sudo systemctl status lpc 