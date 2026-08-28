import hashlib
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Create a consistent, hash-verified backup of the local SQLite database.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--output-dir',
            default=str(settings.BASE_DIR / 'backups'),
            help='Directory that will receive the timestamped backup.',
        )

    def handle(self, *args, **options):
        database = settings.DATABASES['default']
        if database['ENGINE'] != 'django.db.backends.sqlite3':
            raise CommandError(
                'This command handles SQLite only. Use the database provider backup '
                'service plus a tested mysqldump restore procedure for MySQL.'
            )

        source = Path(database['NAME']).resolve()
        if not source.is_file():
            raise CommandError(f'Database does not exist: {source}')

        output_dir = Path(options['output_dir']).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%SZ')
        destination = output_dir / f'asset-tracker-{timestamp}.sqlite3'
        temporary = output_dir / f'.{destination.name}.partial'
        if source == destination or source == temporary:
            raise CommandError('Backup destination must differ from the live database.')

        try:
            # sqlite3.Connection's context manager commits or rolls back but does
            # not close the handle. Explicit closing is required before the
            # atomic rename, especially on Windows.
            with closing(sqlite3.connect(source)) as source_db:
                with closing(sqlite3.connect(temporary)) as backup_db:
                    source_db.backup(backup_db)
            digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
            temporary.replace(destination)
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            raise CommandError(f'Backup failed: {exc}') from exc

        self.stdout.write(self.style.SUCCESS(f'Backup: {destination}'))
        self.stdout.write(self.style.SUCCESS(f'SHA-256: {digest}'))
