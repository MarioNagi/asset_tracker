from django.conf import settings
from django.core.checks import Error, Tags, Warning, register


@register(Tags.security, deploy=True)
def production_configuration_check(app_configs, **kwargs):
    """Fail the deployment check for unsafe or incomplete production wiring.

    The PythonAnywhere target accepts infrastructure differences that the
    self-hosted target forbids: SQLite is the supported primary database,
    the local-memory cache is acceptable for the single-process web app,
    and Celery is replaced by the ``run_scheduled_tasks`` management
    command. Everything else (host whitelist, SMTP, CSRF origins, HSTS
    enablement) is still enforced the same way.
    """
    issues = []
    database = settings.DATABASES['default']
    is_pythonanywhere = getattr(settings, 'IS_PYTHONANYWHERE', False)
    use_celery = getattr(settings, 'USE_CELERY', True)

    if database['ENGINE'] == 'django.db.backends.sqlite3' and not is_pythonanywhere:
        issues.append(Error(
            'SQLite is not approved for the multi-user production deployment.',
            hint='Configure DJANGO_DATABASE_ENGINE=mysql and the DJANGO_DATABASE_* values, '
                 'or set DJANGO_DEPLOYMENT_TARGET=pythonanywhere for the managed host.',
            id='tracking.E001',
        ))
    if '*' in settings.ALLOWED_HOSTS:
        issues.append(Error(
            'DJANGO_ALLOWED_HOSTS must not contain a wildcard in production.',
            id='tracking.E002',
        ))
    if settings.EMAIL_BACKEND.endswith('smtp.EmailBackend') and not settings.EMAIL_HOST:
        issues.append(Error(
            'SMTP email is selected but DJANGO_EMAIL_HOST is empty.',
            id='tracking.E003',
        ))
    if settings.EMAIL_USE_TLS and settings.EMAIL_USE_SSL:
        issues.append(Error(
            'SMTP TLS and SSL cannot both be enabled.',
            hint='Choose DJANGO_EMAIL_USE_TLS or DJANGO_EMAIL_USE_SSL for the provider.',
            id='tracking.E008',
        ))
    if not settings.CSRF_TRUSTED_ORIGINS:
        issues.append(Error(
            'DJANGO_CSRF_TRUSTED_ORIGINS must contain the production HTTPS origin.',
            id='tracking.E004',
        ))
    if 'LocMemCache' in settings.CACHES['default']['BACKEND'] and not is_pythonanywhere:
        issues.append(Error(
            'The local-memory cache cannot enforce shared login rate limits across workers.',
            hint='Set DJANGO_CACHE_URL to the production Redis cache database.',
            id='tracking.E005',
        ))
    if use_celery:
        for setting_name in ('CELERY_BROKER_URL', 'CELERY_RESULT_BACKEND'):
            value = getattr(settings, setting_name, '')
            if not value or '127.0.0.1' in value or 'localhost' in value:
                issues.append(Error(
                    f'{setting_name} is not configured for production infrastructure.',
                    id='tracking.E006' if setting_name == 'CELERY_BROKER_URL' else 'tracking.E007',
                ))
    if settings.SECURE_HSTS_SECONDS == 0 and not is_pythonanywhere:
        issues.append(Warning(
            'HSTS is disabled. Enable it only after the production HTTPS domain is verified.',
            id='tracking.W001',
        ))
    if is_pythonanywhere and not getattr(settings, 'USE_CELERY', True):
        issues.append(Warning(
            'Celery is disabled. Schedule the run_scheduled_tasks management command '
            'from a PythonAnywhere scheduled task so reminders still run.',
            id='tracking.W002',
        ))
    return issues
