#!/bin/bash
sudo find /var/www/lpc -type d -exec chmod 2775 {} \;
sudo find /var/www/lpc -type f -exec chmod 664 {} \;
sudo chmod 660 /var/www/lpc/.env.production
sudo chmod 660 /var/www/lpc/django.log
sudo chown -R ubuntu:www-data /var/www/lpc