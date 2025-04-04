# Generated by Django 5.1.7 on 2025-03-23 19:10

from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('teams', '0027_restructure_profile_data'),
    ]

    operations = [
        migrations.AddField(
            model_name='match',
            name='is_official',
            field=models.BooleanField(default=False, help_text='Indicates if this is an official match'),
        ),
        migrations.AddField(
            model_name='playermatchstats',
            name='is_mvp',
            field=models.BooleanField(default=False, help_text='Indicates if the player was MVP of this match'),
        ),
    ] 