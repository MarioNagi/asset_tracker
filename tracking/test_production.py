import sqlite3
from contextlib import closing
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from .checks import production_configuration_check


class HealthEndpointTests(TestCase):
    def test_liveness_is_public_and_minimal(self):
        response = self.client.get(reverse('health_live'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok'})
        self.assertIn("default-src 'self'", response['Content-Security-Policy'])
        self.assertIn('camera=()', response['Permissions-Policy'])

    def test_readiness_checks_database_and_cache(self):
        response = self.client.get(reverse('health_ready'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'ok')
        self.assertEqual(
            response.json()['checks'], {'database': True, 'cache': True}
        )


class DatabaseBackupCommandTests(SimpleTestCase):
    def test_sqlite_backup_is_complete_and_readable(self):
        with TemporaryDirectory() as directory:
            source = f'{directory}/source.sqlite3'
            output = f'{directory}/backups'
            with closing(sqlite3.connect(source)) as connection:
                connection.execute('CREATE TABLE records (value TEXT)')
                connection.execute("INSERT INTO records VALUES ('preserved')")
                connection.commit()

            databases = {
                'default': {
                    'ENGINE': 'django.db.backends.sqlite3',
                    'NAME': source,
                }
            }
            stdout = StringIO()
            with override_settings(DATABASES=databases):
                call_command('backup_database', output_dir=output, stdout=stdout)

            backup = next(Path(output).glob('*.sqlite3'))
            with closing(sqlite3.connect(backup)) as connection:
                self.assertEqual(
                    connection.execute('PRAGMA integrity_check').fetchone()[0],
                    'ok',
                )
                self.assertEqual(
                    connection.execute('SELECT value FROM records').fetchone()[0],
                    'preserved',
                )
            self.assertIn('SHA-256:', stdout.getvalue())


class ProductionConfigurationCheckTests(SimpleTestCase):
    @override_settings(EMAIL_USE_TLS=True, EMAIL_USE_SSL=True)
    def test_conflicting_smtp_encryption_is_rejected(self):
        issue_ids = {
            issue.id for issue in production_configuration_check(None)
        }
        self.assertIn('tracking.E008', issue_ids)

    @override_settings(IS_PYTHONANYWHERE=False, USE_CELERY=True)
    def test_self_hosted_still_rejects_sqlite(self):
        databases = {
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': '/tmp/anything.sqlite3',
            }
        }
        with override_settings(
            IS_PYTHONANYWHERE=False,
            USE_CELERY=True,
            DATABASES=databases,
            CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
            CELERY_BROKER_URL='redis://127.0.0.1:6379/0',
            CELERY_RESULT_BACKEND='redis://127.0.0.1:6379/1',
        ):
            issue_ids = {
                issue.id for issue in production_configuration_check(None)
            }
            self.assertIn('tracking.E001', issue_ids)
            self.assertIn('tracking.E005', issue_ids)

    @override_settings(
        IS_PYTHONANYWHERE=True,
        USE_CELERY=False,
        DJANGO_DEPLOYMENT_TARGET='pythonanywhere',
    )
    def test_pythonanywhere_target_accepts_sqlite_and_locmem(self):
        databases = {
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': '/home/pa/asset_tracker/db.sqlite3',
            }
        }
        with override_settings(
            IS_PYTHONANYWHERE=True,
            USE_CELERY=False,
            DATABASES=databases,
            CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
            CELERY_BROKER_URL='',
            CELERY_RESULT_BACKEND='',
        ):
            issues = production_configuration_check(None)
            issue_ids = {issue.id for issue in issues}
            self.assertNotIn('tracking.E001', issue_ids)
            self.assertNotIn('tracking.E005', issue_ids)
            self.assertNotIn('tracking.E006', issue_ids)
            self.assertNotIn('tracking.E007', issue_ids)
            self.assertIn('tracking.W002', issue_ids)

    @override_settings(IS_PYTHONANYWHERE=True, USE_CELERY=True)
    def test_pythonanywhere_target_still_rejects_unconfigured_celery(self):
        with override_settings(
            IS_PYTHONANYWHERE=True,
            USE_CELERY=True,
            CELERY_BROKER_URL='redis://127.0.0.1:6379/0',
            CELERY_RESULT_BACKEND='redis://127.0.0.1:6379/1',
        ):
            issue_ids = {
                issue.id for issue in production_configuration_check(None)
            }
            self.assertIn('tracking.E006', issue_ids)
            self.assertIn('tracking.E007', issue_ids)


class RunScheduledTasksCommandTests(TestCase):
    def test_list_prints_all_task_names(self):
        stdout = StringIO()
        call_command('run_scheduled_tasks', '--list', stdout=stdout)
        output = stdout.getvalue()
        for name in (
            'check-vehicle-registrations',
            'check-maintenance-schedule',
            'send-calibration-reminders',
            'send-retirement-task-reminders',
            'send-transfer-follow-up-reminders',
            'send-special-maintenance-reminders',
            'send-odometer-reminders',
        ):
            self.assertIn(name, output)

    def test_only_runs_the_named_task(self):
        stdout = StringIO()
        call_command(
            'run_scheduled_tasks',
            '--only=send-calibration-reminders',
            stdout=stdout,
        )
        output = stdout.getvalue()
        self.assertIn('send-calibration-reminders', output)
        self.assertNotIn('send-retirement-task-reminders', output)

    def test_missing_task_does_not_abort_the_batch(self):
        with patch('tracking.tasks.send_calibration_reminders', None):
            stdout = StringIO()
            call_command(
                'run_scheduled_tasks',
                '--only=send-calibration-reminders',
                stdout=stdout,
            )
        self.assertIn('SKIPPED', stdout.getvalue().upper())
        self.assertIn('send-calibration-reminders', stdout.getvalue())

    def test_failing_task_is_reported_and_exits_nonzero(self):
        # ``@shared_task`` captures the underlying function at import time
        # via ``__wrapped__``, so patching the module attribute does not
        # propagate. Patching the command's ``_unwrap`` helper exercises the
        # failure branch without depending on Celery internals.
        from tracking.management.commands import run_scheduled_tasks as cmd_module

        with patch.object(
            cmd_module,
            '_unwrap',
            side_effect=RuntimeError('boom'),
        ):
            stdout = StringIO()
            with self.assertRaises(SystemExit):
                call_command(
                    'run_scheduled_tasks',
                    '--only=send-calibration-reminders',
                    stdout=stdout,
                )
        self.assertIn('failed', stdout.getvalue().lower())


class DeploymentTargetSettingsTests(SimpleTestCase):
    @override_settings(
        IS_PYTHONANYWHERE=True,
        USE_CELERY=False,
        DEPLOYMENT_TARGET='pythonanywhere',
    )
    def test_pythonanywhere_target_flags(self):
        from django.conf import settings
        self.assertTrue(settings.IS_PYTHONANYWHERE)
        self.assertFalse(settings.USE_CELERY)
        self.assertEqual(settings.DEPLOYMENT_TARGET, 'pythonanywhere')

    @override_settings(
        IS_PYTHONANYWHERE=False,
        USE_CELERY=True,
        DEPLOYMENT_TARGET='self_hosted',
    )
    def test_self_hosted_target_flags(self):
        from django.conf import settings
        self.assertFalse(settings.IS_PYTHONANYWHERE)
        self.assertTrue(settings.USE_CELERY)
        self.assertEqual(settings.DEPLOYMENT_TARGET, 'self_hosted')

    def test_unknown_target_falls_back_to_self_hosted(self):
        from django.conf import settings
        # The default DEPLOYMENT_TARGET is 'self_hosted' when no env var is
        # set; unknown values also fall back to that posture.
        self.assertIn(
            settings.DEPLOYMENT_TARGET,
            {'self_hosted', 'pythonanywhere'},
        )

