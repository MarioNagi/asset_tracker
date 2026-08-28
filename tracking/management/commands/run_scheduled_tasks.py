"""Run all Celery Beat-scheduled tasks synchronously.

This command is the PythonAnywhere-compatible replacement for Celery
Beat. PythonAnywhere cannot run a long-lived Beat process, so a
PythonAnywhere scheduled task is configured to invoke this command once
per hour. Each reminder is isolated in its own try/except block so a
failure in one task never blocks the rest of the batch.

When ``DJANGO_USE_CELERY`` is true the same tasks are still dispatched
through Celery in production. Calling the underlying Python functions
directly works in both modes because the tasks use the standard
``@shared_task`` decorator and do not require a running broker.
"""
import logging

from django.core.management.base import BaseCommand

from tracking import tasks

logger = logging.getLogger(__name__)


# Mirrors ``asset_tracker.celery.app.conf.beat_schedule`` so the two
# schedulers stay in lock-step.
SCHEDULED_TASKS = (
    ('check-vehicle-registrations', 'check_vehicle_registrations'),
    ('check-maintenance-schedule', 'check_maintenance_schedule'),
    ('send-calibration-reminders', 'send_calibration_reminders'),
    ('send-retirement-task-reminders', 'send_retirement_task_reminders'),
    ('send-transfer-follow-up-reminders', 'send_transfer_follow_up_reminders'),
    ('send-special-maintenance-reminders', 'send_special_maintenance_reminders'),
    ('send-odometer-reminders', 'send_weekly_odometer_reminders'),
)


def _unwrap(shared_task_proxy):
    """Return the underlying function behind a ``@shared_task`` proxy.

    ``@shared_task`` returns a ``celery.local.Proxy`` that dispatches to a
    Celery worker when called. We want to invoke the function in-process
    here so the management command does not need a broker connection.
    """
    target = getattr(shared_task_proxy, '__wrapped__', None)
    if target is None:
        target = getattr(shared_task_proxy, 'run', shared_task_proxy)
    return target


class Command(BaseCommand):
    help = (
        'Run the registered reminder tasks synchronously. '
        'Use this from a PythonAnywhere scheduled task when Celery is disabled.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--only',
            action='append',
            choices=[name for name, _ in SCHEDULED_TASKS],
            help='Run only the named task(s). May be repeated.',
        )
        parser.add_argument(
            '--list',
            action='store_true',
            help='Print the scheduled task names and exit.',
        )

    def handle(self, *args, **options):
        if options['list']:
            for name, func in SCHEDULED_TASKS:
                self.stdout.write(f'{name}\t{func}')
            return

        selected = set(options['only']) if options['only'] else None
        results = []
        for name, func_name in SCHEDULED_TASKS:
            if selected and name not in selected:
                continue
            task = getattr(tasks, func_name, None)
            if task is None:
                self.stderr.write(f'Skipping {name}: tracking.tasks.{func_name} is missing.')
                results.append((name, 'missing'))
                continue
            try:
                _unwrap(task)()
            except Exception:
                # The internal task helpers already isolate per-record errors,
                # so a traceback here is a real bug we want surfaced.
                logger.exception('Scheduled task %s failed.', name)
                results.append((name, 'failed'))
            else:
                results.append((name, 'ok'))

        ok = sum(1 for _, status in results if status == 'ok')
        failed = sum(1 for _, status in results if status == 'failed')
        skipped = sum(1 for _, status in results if status == 'missing')
        self.stdout.write(self.style.SUCCESS(
            f'run_scheduled_tasks complete: {ok} ok, {failed} failed, {skipped} skipped.'
        ))
        for name, status in results:
            label = self.style.SUCCESS('OK') if status == 'ok' else self.style.ERROR(status.upper())
            self.stdout.write(f'  {label}\t{name}')
        if failed:
            raise SystemExit(1)
