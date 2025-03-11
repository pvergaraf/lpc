#!/bin/bash
set -a
source /var/www/lpc/.env.production
set +a

cd /var/www/lpc
source venv/bin/activate
python scripts/test_s3.py