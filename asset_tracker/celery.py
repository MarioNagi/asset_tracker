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
    'check-tire-schedule': {
        'task': 'tracking.tasks.check_tire_schedule',
        'schedule': crontab(hour=10, minute=0),  # Run daily at 10 AM
    },
}
