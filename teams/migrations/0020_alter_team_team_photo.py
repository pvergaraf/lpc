# Generated by Django 5.1.7 on 2025-03-12 04:26

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('teams', '0019_team_team_photo_alter_profile_country'),
    ]

    operations = [
        migrations.AlterField(
            model_name='team',
            name='team_photo',
            field=models.ImageField(blank=True, default='team_photos/default.png', help_text='Upload a square team photo', upload_to='team_photos/'),
        ),
    ]
