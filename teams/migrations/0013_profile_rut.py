# Generated by Django 5.1.7 on 2025-03-10 20:38

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('teams', '0012_profile_is_official'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='rut',
            field=models.CharField(blank=True, help_text='Chilean ID number (RUT)', max_length=12, null=True),
        ),
    ]
