# Deployment Guide

## Local Development Setup

### Prerequisites
- Python 3.8 or higher
- PostgreSQL
- Git

### Local Setup Steps

1. Clone the repository:
```bash
git clone https://github.com/pvergaraf/lpc.git
cd lpc
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Create a `.env` file in the project root:
```bash
DEBUG=True
SECRET_KEY=your-secret-key
DATABASE_URL=postgresql://user:password@localhost:5432/lpc_db
AWS_ACCESS_KEY_ID=your-aws-access-key
AWS_SECRET_ACCESS_KEY=your-aws-secret-key
AWS_STORAGE_BUCKET_NAME=your-bucket-name
AWS_S3_REGION_NAME=your-region
```

5. Run migrations:
```bash
python manage.py migrate
```

6. Create a superuser:
```bash
python manage.py createsuperuser
```

7. Run the development server:
```bash
python manage.py runserver
```

## Production Deployment (AWS)

### Prerequisites
- AWS Account
- EC2 Instance (Ubuntu)
- RDS PostgreSQL Database
- S3 Bucket
- Domain Name (optional)

### Server Setup

1. Connect to your EC2 instance:
```bash
ssh -i your-key.pem ubuntu@your-server-ip
```

2. Install required packages:
```bash
sudo apt update
sudo apt install python3-pip python3-venv nginx git postgresql-client
```

3. Clone the repository:
```bash
cd /var/www
sudo mkdir lpc
sudo chown ubuntu:ubuntu lpc
git clone https://github.com/pvergaraf/lpc.git lpc
cd lpc
```

4. Create and activate virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate
```

5. Install dependencies:
```bash
pip install -r requirements.txt
pip install gunicorn
```

6. Create `.env.production` file:
```bash
DEBUG=False
SECRET_KEY=your-secure-secret-key
DATABASE_URL=postgresql://user:password@your-rds-endpoint:5432/lpc_db
ALLOWED_HOSTS=your-domain.com,www.your-domain.com
AWS_ACCESS_KEY_ID=your-aws-access-key
AWS_SECRET_ACCESS_KEY=your-aws-secret-key
AWS_STORAGE_BUCKET_NAME=your-bucket-name
AWS_S3_REGION_NAME=your-region
```

7. Set up Gunicorn service:
```bash
sudo nano /etc/systemd/system/lpc.service
```

Add the following content:
```ini
[Unit]
Description=LPC Gunicorn Daemon
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/lpc
Environment="PATH=/var/www/lpc/venv/bin"
EnvironmentFile=/var/www/lpc/.env.production
ExecStart=/var/www/lpc/venv/bin/gunicorn --workers 3 --bind unix:/var/www/lpc/lpc.sock club_project.wsgi:application

[Install]
WantedBy=multi-user.target
```

8. Set up Nginx:
```bash
sudo nano /etc/nginx/sites-available/lpc
```

Add the following content:
```nginx
server {
    listen 80;
    server_name your-domain.com www.your-domain.com;

    location = /favicon.ico { access_log off; log_not_found off; }
    
    location /static/ {
        alias /var/www/lpc/staticfiles/;
    }

    location /media/ {
        alias /var/www/lpc/mediafiles/;
    }

    location / {
        include proxy_params;
        proxy_pass http://unix:/var/www/lpc/lpc.sock;
    }
}
```

9. Enable the site:
```bash
sudo ln -s /etc/nginx/sites-available/lpc /etc/nginx/sites-enabled
sudo nginx -t
sudo systemctl restart nginx
```

10. Set proper permissions:
```bash
sudo chown -R www-data:www-data /var/www/lpc
sudo chmod -R 755 /var/www/lpc
sudo chown -R ubuntu:ubuntu /var/www/lpc/.git
```

11. Collect static files and run migrations:
```bash
python manage.py collectstatic --no-input
python manage.py migrate
```

12. Start Gunicorn:
```bash
sudo systemctl start lpc
sudo systemctl enable lpc
```

### Deployment Script

Create a deployment script (`~/deploy.sh`):
```bash
#!/bin/bash
cd /var/www/lpc

# Set permissions for git operations
sudo chown -R ubuntu:ubuntu /var/www/lpc

# Pull latest changes
git reset --hard HEAD
git clean -fd
git pull origin main

# Install any new dependencies
source venv/bin/activate
pip install -r requirements.txt

# Collect static files and run migrations
python manage.py collectstatic --no-input
python manage.py migrate

# Reset permissions
sudo chown -R www-data:www-data /var/www/lpc
sudo chmod -R 755 /var/www/lpc
sudo chown -R ubuntu:ubuntu /var/www/lpc/.git

# Restart services
sudo systemctl restart lpc
```

Make the script executable:
```bash
chmod +x ~/deploy.sh
```

### SSL Certificate (Optional)

To enable HTTPS:
```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com -d www.your-domain.com
```

### Monitoring Logs

To monitor application logs:
```bash
sudo journalctl -u lpc.service -f
```

To monitor Nginx logs:
```bash
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
``` 