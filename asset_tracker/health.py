import logging

from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET


logger = logging.getLogger(__name__)


@require_GET
def live(request):
    """Process liveness endpoint for the reverse proxy/orchestrator."""
    return JsonResponse({'status': 'ok'})


@require_GET
def ready(request):
    """Readiness endpoint covering the shared state required to serve users."""
    checks = {'database': False, 'cache': False}
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
        checks['database'] = True
    except Exception:
        logger.exception('Readiness database check failed.')

    try:
        cache_key = 'asset-tracker-readiness'
        cache.set(cache_key, 'ok', timeout=10)
        checks['cache'] = cache.get(cache_key) == 'ok'
    except Exception:
        logger.exception('Readiness cache check failed.')

    ready_status = all(checks.values())
    return JsonResponse(
        {'status': 'ok' if ready_status else 'unavailable', 'checks': checks},
        status=200 if ready_status else 503,
    )
