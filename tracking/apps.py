# tracking/apps.py

from django.apps import AppConfig

class TrackingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tracking'

    def ready(self):
        import tracking.signals
        import tracking.checks
