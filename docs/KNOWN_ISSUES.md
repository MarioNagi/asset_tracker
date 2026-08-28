# Production gaps and known limitations

Last reviewed: 28 August 2026.

This is the launch-truth document. “Implemented” means code and automated tests
exist. It does not mean external infrastructure or company acceptance has happened.

## P0 — launch blockers

- **Credential exposure response:** four account password hashes existed in pushed database commits `6bdece5` and `b2bfbb4`. Rotate those account passwords, the Django secret, and any database/email credentials that may have been present. Decide with every repository user whether to rewrite shared history, then run an approved full-history secret scan.
- **Production infrastructure:** the codebase is now selectable between a PythonAnywhere target (managed host, SQLite, no Celery, `run_scheduled_tasks` driven by a PythonAnywhere scheduled task) and a self-hosted target (MySQL, Redis, Gunicorn, Celery worker + Beat). Either way, the platform account, the SMTP mailbox, the backup destination, and the monitoring target still have to be provisioned by an operator with that account's credentials. No production platform has been supplied or accepted in this workspace.
- **Restore proof:** restore a production-format backup into an isolated environment and verify record counts, login, 2FA, files, transfers, invoices, and reports. A successful backup command alone is insufficient.
- **Email acceptance:** configure approved alert mailboxes and SMTP credentials, test every required event with test recipients, verify Delivery History/failure retry, and only then enable the production reminder schedule (Celery Beat on self-hosted, `run_scheduled_tasks` on PythonAnywhere).
- **Historical data review:** confirm operational databases, exports, invoices, and photos are stored outside Git with correct access and retention controls.
- **Release source-control review:** Git currently refuses repository operations because the workspace owner SID differs from the running account. The repository owner/administrator must correct ownership or explicitly approve the repository as safe, then review and commit the intended release changes. No commit was created during this work.

## P1 — required before broad rollout

- Tool lifecycle/history values and disposal workflow are not implemented. Current Tool profiles, custody, calibration, controlled-device fields, catalogue, and ledger work, but Tool History, documents, and repair/maintenance history remain incomplete.
- Existing registration, maintenance, and calibration scheduled tasks isolate failures, but registration/maintenance/calibration still need full migration to the audited Delivery History service and complete approved recipient-matrix tests.
- Controlled-device transfer notification routing now uses tracked delivery and origin/destination state resolution, but the complete same-state/cross-state recipient matrix still needs dedicated automated and real-mail acceptance tests.
- Vehicle retirement and transfer-follow-up reminders now use tracked, daily deduplicated deliveries, but must be accepted against real configured mailboxes.
- QR fuel/odometer monitoring and special maintenance are implemented and automated, but still require company acceptance with real vehicle labels, representative phone photos, approved recipients, and fleet-manager operating procedures.
- PDF invoice import is production-shaped for the tested MechanicDesk layout. Other supplier layouts require approved anonymized samples and regression fixtures; low-confidence invoices must continue through manual review.
- Accident creation, permissions, validation, and totals are covered. Dedicated update-flow regression coverage remains incomplete.
- The UI still downloads Font Awesome and Chart.js from approved CDN origins. Bootstrap is now local. Self-host the remaining assets if the company requires offline operation or a stricter Content Security Policy without external origins/inline scripts.
- Production MySQL behavior and query plans have not been exercised because no production-like MySQL instance is available in this workspace. Measure before adding speculative indexes.
- The PythonAnywhere reminder path runs every hour from a scheduled task; the same redundancy and per-record isolation that Celery Beat provided should be re-verified once the real mailbox is configured.

## Deferred, not launch blockers unless scope changes

- Tire tracking and reminders.
- Microsoft Entra ID login and Entra group-to-role/state mapping.
- Teams notifications and controlled-device recipient acknowledgement.
- Cosmetic modernization beyond the current responsive professional baseline.

## Current verified foundation

- Closed public registration, role-scoped access, mandatory Admin/Manager TOTP, stable 2FA enrollment, password validation, login rate limits, secure session/header defaults, upload signature/size checks, image compression, and protected uploaded-file routes.
- Active/retired vehicle lifecycle, financial retirement record, checklist, vehicle history, and retained related records.
- Admin-only source-first batch transfers, multiple/all tools, one car, real company locations, immutable per-asset ledger, reversals, and state-change tasks.
- Controlled-device fields, searchable tool catalogue, Tool profile, calibration state, and custody history.
- Maintenance overview/detail and car drill-down, PDF invoice preview/confirmation, analytics, and exports.
- Printable per-vehicle QR labels, authenticated exact-vehicle entry, seven-day accepted-reading status, mandatory compressed fuel receipts, suspicious-reading review, and tracked overdue reminders.
- Fleet-managed special maintenance by date/odometer with advance windows, recurrence, completion evidence, vehicle summaries, and tracked alerts.
- Environment-driven MySQL/Redis/SMTP/static/media configuration, production deployment checks, liveness/readiness endpoints, scheduled worker configuration, and local consistent database backup command.
- PythonAnywhere deployment target: `DJANGO_DEPLOYMENT_TARGET=pythonanywhere` turns off Celery/Redis requirements, accepts SQLite + the local-memory cache, defaults the security headers to safe values, and exposes the `run_scheduled_tasks` management command for a PythonAnywhere scheduled task. The self-hosted target keeps the original MySQL/Redis/Celery requirements; both targets share the same 131-test regression suite.
- Final local verification: 131 automated tests, clean production-code Bandit scan, no known dependency vulnerabilities, clean production deployment check, verified static collection, and desktop/390-pixel GUI acceptance with a clean fresh console.
