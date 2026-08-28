# Production deployment runbook

This runbook is the minimum supported launch process for Koinonia Asset Tracker.
Do not point employees at the service until every item in the launch gate is
signed off.

## Architecture

- One HTTPS reverse proxy/load balancer.
- Django web processes running Gunicorn.
- MySQL using `utf8mb4`, encrypted connections, automated backups, and point-in-time recovery where available.
- Redis split into broker, Celery result, and Django cache databases.
- Separate Celery worker and Celery Beat services.
- A private persistent media volume. `/media/` must **not** be exposed directly by the reverse proxy; authenticated download routes serve protected files.
- Central log collection and uptime checks for `/health/live/` and `/health/ready/`.

SQLite remains supported for local development and emergency offline recovery only.

## Production environment

Start from `.env.example`, store the real values in the deployment secret store,
and never copy the production file into Git. Required production values include:

- `DJANGO_DEBUG=false`
- a new long random `DJANGO_SECRET_KEY`
- the exact public host in `DJANGO_ALLOWED_HOSTS`
- the exact `https://` origin in `DJANGO_CSRF_TRUSTED_ORIGINS`
- MySQL `DJANGO_DATABASE_*` values and the provider CA where applicable
- non-local Redis URLs for Celery and `DJANGO_CACHE_URL`
- the approved SMTP server and service-account credentials
- secure cookies, SSL redirect, and the confirmed reverse-proxy setting
- the final static and private media paths

Enable HSTS in two stages: first use a short value after HTTPS is verified, then
increase it after confirming every required subdomain is HTTPS-only. Do not enable
subdomain coverage or preload without company/domain-owner approval.

## Build and preflight

Create a clean Python environment from `requirements.txt`; do not reuse the
developer workstation environment.

```text
python -m pip install --requirement requirements.txt
python -m pip check
python manage.py check
python manage.py check --deploy
python manage.py makemigrations --check --dry-run
python manage.py migrate --plan
python manage.py collectstatic --noinput
python manage.py test
```

The deployment check is intentionally fail-closed for SQLite, wildcard hosts,
missing SMTP/CSRF configuration, local-only Redis URLs, and local-memory login
rate limiting.

## Database migration and rollback

1. Put the site into a maintenance window and stop Beat/worker processes.
2. Take a provider snapshot and verify that it completed.
3. Record the running application revision and migration plan.
4. Run `python manage.py migrate` once.
5. Run readiness and a signed-in Admin smoke test.
6. Start the worker, then Beat, and verify their logs.

Rollback means restoring both the previous application revision and the matching
database snapshot. Never reverse an unknown migration against company data merely
to make the code start.

For the current local SQLite database, create a consistent verified backup with:

```text
python manage.py backup_database
```

The command prints the backup path and SHA-256 hash. A backup is not accepted
until a restore into a disposable environment has passed login and record-count
checks. Production MySQL must use provider backups plus a separately tested
`mysqldump`/restore procedure.

## Services

Run these as independently supervised services with automatic restart and logs:

```text
gunicorn asset_tracker.wsgi:application --bind 127.0.0.1:8000 --workers 3 --timeout 120
celery -A asset_tracker worker --loglevel=INFO
celery -A asset_tracker beat --loglevel=INFO
```

Use one Beat instance only. Multiple Beat instances can enqueue duplicate work;
delivery deduplication is a safety net, not a substitute for correct deployment.

## Reverse proxy rules

- Redirect HTTP to HTTPS.
- Pass the original host and `X-Forwarded-Proto` headers.
- Serve `/static/` from `DJANGO_STATIC_ROOT` with immutable cache headers.
- Do not expose `DJANGO_MEDIA_ROOT` or `/media/` directly.
- Proxy application routes, including protected file downloads, to Django.
- Apply request/body limits consistent with the application's 5–15 MB upload limits.

## Email and reminders acceptance

Before enabling Beat, use approved test mailboxes to verify registration,
maintenance, calibration, Written off/retirement, controlled-device transfer,
special maintenance, weekly odometer escalation, retirement-checklist, and
transfer-follow-up messages. Confirm recipients and
absence of unrelated recipients in Delivery History. Then enable Beat and watch
one complete scheduled cycle.

Print a small pilot set of vehicle QR labels and test them with the phone models
employees actually use. Confirm login handoff, the correct registration/photo,
receipt readability after compression, suspicious-reading review, and that a QR
submission never changes formal vehicle custody.

## Monitoring

- `/health/live/`: process is running.
- `/health/ready/`: database and shared cache are usable.
- Alert on HTTP 5xx, readiness failures, failed notification deliveries, worker/Beat silence, database capacity, Redis capacity, disk/media capacity, and backup failure.
- Keep application and security logs centrally with access controls and a company-approved retention period.

## Launch gate

Production approval requires all P0 items in `docs/KNOWN_ISSUES.md` to be closed,
the complete automated suite to pass on the release revision, a restored backup
test, and signed-in acceptance for Admin, Manager, and User roles on desktop and
mobile.
