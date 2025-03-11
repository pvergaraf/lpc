#!/bin/bash

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

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install/update dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

# Collect static files
echo "Collecting static files..."
python manage.py collectstatic --noinput

# Apply database migrations
echo "Applying database migrations..."
python manage.py migrate

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

echo "Deployment completed successfully!"