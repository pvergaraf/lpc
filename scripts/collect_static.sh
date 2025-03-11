#!/bin/bash
set -a
source /var/www/lpc/.env.production
set +a

export DEBUG=False

cd /var/www/lpc
source venv/bin/activate

echo "Removing old static files..."
rm -rf /var/www/lpc/staticfiles/*

echo "Removing Python cache files..."
find . -type d -name "__pycache__" -exec rm -r {} + 2>/dev/null || true
find . -name "*.pyc" -delete

echo "Collecting static files with maximum verbosity..."
PYTHONPATH=/var/www/lpc python manage.py collectstatic --no-input -v 3 --clear

echo "Verifying S3 upload..."
python scripts/test_s3.py