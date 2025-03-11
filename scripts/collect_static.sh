#!/bin/bash
set -a
source /var/www/lpc/.env.production
set +a

export DEBUG=False

cd /var/www/lpc
source venv/bin/activate

echo "Removing old static files..."
rm -rf /var/www/lpc/staticfiles/*

echo "Collecting static files..."
python manage.py collectstatic --no-input -v 3 --clear