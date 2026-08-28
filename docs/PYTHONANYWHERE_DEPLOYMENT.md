# PythonAnywhere deployment

This runbook covers the minimum-supported launch process for the
Koinonia Asset Tracker on a [PythonAnywhere](https://www.pythonanywhere.com/)
account. The same Django code base runs on a self-hosted Linux box too;
this document only describes the differences.

PythonAnywhere is a managed platform, so some launch-gate items from
`PRODUCTION_DEPLOYMENT.md` (HTTPS termination, process supervision,
infrastructure provisioning) are already handled for you. Others —
real SMTP acceptance, company-user acceptance, restore proof, and
credential rotation — still have to be done before employees go live.

## What changes for PythonAnywhere

- **Celery is disabled.** A long-lived worker or Beat process is not
  supported. The `run_scheduled_tasks` management command replaces Beat
  and is invoked from a PythonAnywhere scheduled task once per hour.
- **Redis is not required.** The local-memory cache is fine for a
  single-process web app. Set `DJANGO_CACHE_URL` only if you upgrade
  to a paid plan and want a shared Memcached.
- **SQLite is the default primary database.** PythonAnywhere's free
  tier does not expose MySQL; the managed MySQL add-on is available
  on paid plans and the existing `DJANGO_DATABASE_ENGINE=mysql`
  configuration keeps working there. A small fleet of users fits
  comfortably on SQLite; upgrade when concurrent writes start
  competing.
- **HTTPS is automatic** on the `*.pythonanywhere.com` domain. Set
  `DJANGO_DEPLOYMENT_TARGET=pythonanywhere` and the security settings
  default to the safe values.
- **Static and media files are served by the PythonAnywhere web
  server.** They are mapped in the Web tab; Django itself does not
  serve them in production.
- **`DJANGO_BEHIND_HTTPS_PROXY=true`** is the default, because
  PythonAnywhere forwards `X-Forwarded-Proto: https`.

## One-time account setup

1. Create a PythonAnywhere account (a paid plan is required for the
   MySQL add-on, custom domains, hourly scheduled tasks, and
   always-on tasks; the free tier is enough for an evaluation).
2. Open a Bash console and clone the repository:

   ```bash
   cd ~
   git clone <your-git-url> asset_tracker
   ```

3. Create the virtual environment and install pinned requirements.
   Python 3.12 is available on all current plans:

   ```bash
   cd ~/asset_tracker
   python3.12 -m venv .venv
   source .venv/bin/activate
   python -m pip install --upgrade pip
   python -m pip install --requirement requirements.txt
   python -m pip check
   ```

4. Create `.env` from `.env.example` and fill in the
   PythonAnywhere-specific values. The minimum required keys are
   documented in the next section.

5. Run the preflight checks against the live SQLite database:

   ```bash
   python manage.py migrate
   python manage.py check
   python manage.py check --deploy
   python manage.py collectstatic --noinput
   python manage.py test
   ```

   The `--deploy` check is now aware of the PythonAnywhere target
   and will only fail on real configuration problems (wildcard hosts,
   empty SMTP host, etc.).

## `.env` template for PythonAnywhere

```dotenv
DJANGO_DEPLOYMENT_TARGET=pythonanywhere
DJANGO_DEBUG=false
DJANGO_SECRET_KEY=<generate-with-secrets.token_urlsafe-64>
DJANGO_ALLOWED_HOSTS=<your-username>.pythonanywhere.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://<your-username>.pythonanywhere.com
DJANGO_TIME_ZONE=Australia/Sydney
DJANGO_DATABASE_ENGINE=sqlite
DJANGO_DATABASE_NAME=/home/<your-username>/asset_tracker/db.sqlite3
DJANGO_USE_CELERY=false
DJANGO_EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
DJANGO_EMAIL_HOST=smtp.gmail.com
DJANGO_EMAIL_PORT=587
DJANGO_EMAIL_HOST_USER=<alert-mailbox>
DJANGO_EMAIL_HOST_PASSWORD=<app-password>
DJANGO_EMAIL_USE_TLS=true
DJANGO_DEFAULT_FROM_EMAIL=Koinonia Enterprises <no-reply@example.com>
DJANGO_FLEET_MANAGER_EMAIL=fleet.manager@example.com
DJANGO_STATIC_ROOT=/home/<your-username>/asset_tracker/staticfiles
DJANGO_MEDIA_ROOT=/home/<your-username>/asset_tracker/media
DJANGO_MFA_REQUIRED_ROLES=Admin,Manager
```

Use a real long random value for `DJANGO_SECRET_KEY`. PythonAnywhere
exposes the value in the Web tab env-var panel, but keeping it in
`.env` makes the same file work across local, staging, and
production.

## Web app configuration

In the **Web** tab:

1. **Add a new web app** → **Manual configuration** → **Python 3.12**.
2. Set the **virtualenv** path to `/home/<your-username>/asset_tracker/.venv`.
3. Set the **WSGI configuration file** path to
   `/home/<your-username>/asset_tracker/wsgi.py` (copy
   `pythonanywhere_wsgi.py` to that path first).
4. Add **static files** mappings:
   - URL `/static/`, directory `/home/<your-username>/asset_tracker/staticfiles`
   - URL `/media/`, directory `/home/<your-username>/asset_tracker/media`
5. Add **environment variables** if you prefer not to use `.env`
   (the WSGI loader leaves pre-set variables alone).
6. Click **Reload** to start the app.

Visit `https://<your-username>.pythonanywhere.com/health/ready/` —
a 200 response with `{"status": "ok"}` confirms the database and
cache are reachable. Visit `https://<your-username>.pythonanywhere.com/`
to land on the sign-in page.

## Scheduled reminders

PythonAnywhere paid plans run user-scheduled tasks once per hour. Open
the **Tasks** tab and create a new scheduled task:

- **Time:** any hour, every hour (for example `0 * * * *`).
- **Command:**

  ```bash
  cd /home/<your-username>/asset_tracker && \
    /home/<your-username>/asset_tracker/.venv/bin/python \
    manage.py run_scheduled_tasks >> /home/<your-username>/asset_tracker/logs/scheduled-tasks.log 2>&1
  ```

Create the `logs/` directory first. The command runs all seven
registered reminders (registration, maintenance, calibration,
retirement, transfer follow-up, special maintenance, weekly odometer)
and exits non-zero if any task crashes. Use `--only=send-calibration-reminders`
to run a single task during smoke tests. Use `--list` to see the
registered task names.

On the free tier, scheduled tasks are limited to one per day. While
that is in use, run the command manually from a Bash console at a
suitable interval. The reminders are designed to be safe to invoke
multiple times in a day; each delivery is deduplicated.

## Backups

The `backup_database` management command works against the local
SQLite database and prints a SHA-256 hash. Schedule a daily backup
the same way as the reminder command:

```bash
cd /home/<your-username>/asset_tracker && \
  /home/<your-username>/asset_tracker/.venv/bin/python \
  manage.py backup_database --output-dir /home/<your-username>/asset_tracker/backups \
  >> /home/<your-username>/asset_tracker/logs/backup.log 2>&1
```

Download the resulting `*.sqlite3` file (and its hash) to a separate
location regularly. A backup is only accepted after a restore into a
disposable environment has passed login and record-count checks.

## Email acceptance

Configure `DJANGO_EMAIL_*` with a real SMTP service. Google Workspace
and Microsoft 365 both work with an app password; transactional
providers (Mailgun, Postmark, SendGrid) are also suitable. The
frequent SMTP providers require `EMAIL_USE_TLS=true` and port `587`.

Send a test registration, maintenance, calibration, retirement,
transfer follow-up, special maintenance, and weekly odometer reminder
before enabling the scheduled task. The **Email Alerts → Delivery
History** view records the message, recipient set, and outcome. Failed
deliveries can be retried by an administrator from the same view.

## Monitoring

PythonAnywhere surfaces the web app's response codes and error logs
in the **Web** and **Tasks** tabs. The application's existing
`/health/live/` and `/health/ready/` endpoints are still useful for
external uptime checks (UptimeRobot, Better Stack, or similar). The
readiness check covers the database and cache.

## Upgrading off PythonAnywhere

If the company later moves to a self-hosted box, set
`DJANGO_DEPLOYMENT_TARGET=self_hosted`, install MySQL/Redis, set
`DJANGO_USE_CELERY=true`, and bring the worker and Beat processes
back up. The rest of the configuration is already in place; the
production check will surface the new gaps (SQLite forbidden,
local-memory cache forbidden, broker URL required).

## Launch gate

Production approval still requires the items in `KNOWN_ISSUES.md`
that are not platform-specific: credential rotation, restore proof,
real SMTP acceptance, historical data review, and signed-in user
acceptance for every role.
