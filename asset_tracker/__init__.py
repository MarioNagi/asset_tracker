"""Asset Tracker Django project package.

The Celery app is only wired up when the deployment target requires it.
On the PythonAnywhere target the management command
``run_scheduled_tasks`` replaces Celery Beat and the worker process, so the
import is skipped entirely. This keeps ``manage.py`` and the WSGI entry
point fast to start and avoids loading a broker connection that the
platform does not expose.
"""
import os

if os.getenv('DJANGO_USE_CELERY', 'false').strip().lower() in {'1', 'true', 'yes', 'on'}:
    from .celery import app as celery_app  # noqa: F401
    __all__ = ('celery_app',)
else:
    celery_app = None
    __all__ = ()
