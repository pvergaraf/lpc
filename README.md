# Club Management System

A Django-based team management system that helps sports clubs manage their teams, players, and matches.

## Features

- Team Management
- Player Profiles with Positions
- Match Scheduling
- Season Management
- Member Administration
- RUT (Chilean ID) Integration

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