from __future__ import absolute_import, unicode_literals
import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'asset_tracker.settings')

app = Celery('asset_tracker')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

# Configure the Celery Beat Schedule
app.conf.beat_schedule = {
    'check-vehicle-registrations': {
        'task': 'tracking.tasks.check_vehicle_registrations',
        'schedule': crontab(hour=9, minute=0),  # Run daily at 9 AM
    },
    'check-maintenance-schedule': {
        'task': 'tracking.tasks.check_maintenance_schedule',
        'schedule': crontab(hour=9, minute=30),  # Run daily at 9:30 AM
    },
    'send-calibration-reminders': {
        'task': 'tracking.tasks.send_calibration_reminders',
        'schedule': crontab(hour=10, minute=0),  # Run daily at 10 AM
    },
    'send-retirement-task-reminders': {
        'task': 'tracking.tasks.send_retirement_task_reminders',
        'schedule': crontab(hour=10, minute=30),
    },
    'send-transfer-follow-up-reminders': {
        'task': 'tracking.tasks.send_transfer_follow_up_reminders',
        'schedule': crontab(hour=11, minute=0),
    },
    'send-special-maintenance-reminders': {
        'task': 'tracking.tasks.send_special_maintenance_reminders',
        'schedule': crontab(hour=10, minute=45),
    },
    'send-weekly-odometer-reminders': {
        'task': 'tracking.tasks.send_weekly_odometer_reminders',
        'schedule': crontab(hour=11, minute=15),
    },
}
