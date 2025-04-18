# Generated by Django 5.1.7 on 2025-03-28 15:07

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('teams', '0032_move_slach_account_to_season'),
    ]

    operations = [
        migrations.AlterField(
            model_name='match',
            name='field_number',
            field=models.PositiveIntegerField(blank=True, help_text='Enter the field number', null=True),
        ),
        migrations.AlterField(
            model_name='match',
            name='match_time',
            field=models.TimeField(blank=True, null=True),
        ),
    ]
