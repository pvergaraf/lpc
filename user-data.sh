#!/bin/bash
apt-get update
apt-get install -y python3-pip python3-venv nginx postgresql-client

# Create application directory
mkdir -p /var/www/lpc
cd /var/www/lpc

# Clone the repository
git clone https://github.com/pvergaraf/lpc.git .

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure Nginx
cat > /etc/nginx/sites-available/lpc << 'EOF'
server {
    listen 80;
    server_name _;

    location /static/ {
        alias /var/www/lpc/static/;
    }

    location /media/ {
        alias /var/www/lpc/media/;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
EOF

# Enable the site
ln -s /etc/nginx/sites-available/lpc /etc/nginx/sites-enabled/
rm /etc/nginx/sites-enabled/default

# Restart Nginx
systemctl restart nginx

# Create systemd service
cat > /etc/systemd/system/lpc.service << 'EOF'
[Unit]
Description=LPC Django Application
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/lpc
ExecStart=/var/www/lpc/venv/bin/gunicorn --workers 3 --bind 127.0.0.1:8000 club_project.wsgi:application
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# Start and enable the service
systemctl start lpc
systemctl enable lpc 