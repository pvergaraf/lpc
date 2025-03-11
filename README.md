# Fubol Club

A Django web application for managing soccer teams and matches.

## Environment Configuration

The project uses different environment files for development and production settings:

### Local Development
- Uses `.env` file by default
- Set `DEBUG=True` for development features
- Emails are printed to console instead of being sent
- SQLite database by default

Example `.env` file for development:
```env
DEBUG=True
SECRET_KEY=your-development-secret-key
DB_NAME=db.sqlite3
DB_ENGINE=django.db.backends.sqlite3
SENDGRID_API_KEY=your-sendgrid-key  # Optional in development
```

### Production
- Uses `.env.production` file
- Set `DEBUG=False` for production security
- Emails are sent through SendGrid SMTP
- PostgreSQL database configuration required

Example `.env.production` file:
```env
DEBUG=False
SECRET_KEY=your-super-secret-key-change-this
ALLOWED_HOSTS=your-domain.com,www.your-domain.com

# Database Settings
DB_NAME=your_db_name
DB_USER=your_db_user
DB_PASSWORD=your_db_password
DB_HOST=your.db.host
DB_PORT=5432

# AWS Settings
AWS_ACCESS_KEY_ID=your-aws-key
AWS_SECRET_ACCESS_KEY=your-aws-secret
AWS_STORAGE_BUCKET_NAME=your-bucket-name
AWS_S3_REGION_NAME=your-region

# Email Settings
SENDGRID_API_KEY=your-sendgrid-key
```

### Switching Environments

The application determines which environment file to use based on the `DJANGO_ENV` environment variable:

```bash
# Development (default)
python manage.py runserver

# Production
export DJANGO_ENV=production
python manage.py runserver
```

In production servers, set `DJANGO_ENV=production` in your server configuration (e.g., systemd service file, Docker container, etc.).

## Features

- Team management
- Player profiles
- Season and match scheduling
- Email notifications
- AWS S3 for static and media files
- SendGrid for email delivery (in production)

## Development Setup

1. Clone the repository
2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Create `.env` file with your development settings
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

## Production Deployment

1. Set up your production server (e.g., AWS EC2)
2. Install required packages:
   ```bash
   pip install -r requirements.txt
   ```
3. Create `.env.production` with your production settings
4. Set environment variable:
   ```bash
   export DJANGO_ENV=production
   ```
5. Collect static files:
   ```bash
   python manage.py collectstatic
   ```
6. Configure your web server (e.g., Nginx + Gunicorn)
7. Set up SSL certificates
8. Configure your database
9. Run migrations:
   ```bash
   python manage.py migrate
   ```

## Security Notes

- Never commit `.env` or `.env.production` files to version control
- Keep your secret keys secure
- Always use `DEBUG=False` in production
- Regularly update dependencies
- Use strong passwords for database and admin accounts

## Tech Stack

- Python 3.x
- Django 4.x
- PostgreSQL
- AWS (S3, RDS, EC2)
- Bootstrap 5

## Local Development Setup

1. Clone the repository
```bash
git clone <repository-url>
cd club
```

2. Create and activate virtual environment
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies
```bash
pip install -r requirements.txt
```

4. Set up environment variables
```bash
cp .env.example .env
# Edit .env with your configuration
```

5. Run migrations
```bash
python manage.py migrate
```

6. Create superuser
```bash
python manage.py createsuperuser
```

7. Run development server
```bash
python manage.py runserver
```

## AWS Deployment

The application is configured to run on AWS with:
- EC2 for application hosting
- RDS for PostgreSQL database
- S3 for static and media files

Detailed deployment instructions are in `docs/deployment.md`

## Contributing

1. Fork the repository
2. Create your feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details. 