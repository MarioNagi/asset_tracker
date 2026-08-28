# 🚗 Koinonia Asset Tracker

[![Django 5.2 LTS](https://img.shields.io/badge/Django-5.2_LTS-092E20?logo=django&logoColor=white)](https://www.djangoproject.com/)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-131_passing-brightgreen)](#-testing)
[![PythonAnywhere ready](https://img.shields.io/badge/PythonAnywhere-ready-1589F0)](docs/PYTHONANYWHERE_DEPLOYMENT.md)
[![Self-hosted ready](https://img.shields.io/badge/self--hosted-ready-2E7D32)](docs/PRODUCTION_DEPLOYMENT.md)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20PythonAnywhere-lightgrey)](#-deployment)

A secure, production-ready fleet and asset management platform for **Koinonia
Enterprises**. It manages vehicles, tools, assignments, odometer readings,
maintenance, accidents, supplier invoices, reminders, and fleet reporting
from a single web application.

The codebase has a security-hardened Django 5.2 LTS foundation and a
**131-test regression suite** that covers permissions, 2FA, imports, PDF
parsing, scheduled tasks, and the end-to-end workflows.

---

## ✨ Features

- **Role-based access control** — Admin, Manager (state-scoped), and
  standard User roles with mandatory authenticator-app 2FA for
  privileged accounts
- **Inventory** — Tools and vehicles with full lifecycle, custody
  transfers, controlled-device tracking, and QR-code quick entry
- **Maintenance** — Records, line items, supplier invoice PDF import,
  special-maintenance workspaces, and odometer-based scheduling
- **Reminders** — Registration, maintenance, calibration, retirement,
  transfer follow-up, special maintenance, and weekly odometer alerts
- **Analytics** — Calendar-based dashboard with month/year CSV and
  Excel exports
- **Email** — Admin-managed alert mailbox, responsibility/category
  routing, audited delivery history, deduplication, and safe retry
- **Security** — TOTP 2FA, recovery codes, public registration closed,
  rate-limited login, secure session/header defaults, upload validation
  with image compression, and protected download routes

## 🖼 Screenshots

Screenshots will be added once the live deployment is signed off. The
signed-in application shell, dashboards, vehicle and tool profiles,
maintenance workspace, and PDF import preview are all implemented and
covered by the regression suite.

## 🚀 Quick start (local development)

```bash
git clone https://github.com/MarioNagi/asset_tracker.git
cd asset_tracker

python3.12 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip check

cp .env.example .env             # then edit .env for your local values

python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Sign in at <http://127.0.0.1:8000/>.

> **Windows users:** run every command through
> `.venv\Scripts\python.exe …` rather than a system Python; the
> project pins Django 5.2.17 and django-allauth 65.19.0 and the
> local virtualenv is the supported runtime.

## 🧪 Testing

```bash
python manage.py test tracking
```

The 131-test regression suite covers:

- Role permissions, 2FA enrollment and challenge flows
- Odometer, accident, and maintenance ownership rules
- Tool CSV import, string-keyed transfers, decimal totals
- Vehicle service-state updates, retirement, and follow-up tasks
- PDF invoice parsing for the MechanicDesk layout (anonymized)
- Email Alert routing, deduplication, and safe retry
- Company Location permissions, profiles, and deactivation
- Controlled-device fields, calibration state, and movement history
- Fleet report generation and per-car fuel-efficiency queries
- The `run_scheduled_tasks` management command and the target-aware
  production check

Tests use a disposable in-memory database and never touch the
operational SQLite file.

## 🛠 Tech stack

| Layer | Choice |
|---|---|
| Language | Python 3.12 |
| Web framework | Django 5.2.17 (LTS) |
| Auth | django-allauth 65.19.0 with built-in TOTP MFA + recovery codes |
| Database | MySQL 8, PostgreSQL 16, or SQLite (target-selected) |
| Cache / queue | Redis 7 on the self-hosted target; local-memory cache on PythonAnywhere |
| Background tasks | Celery 5.3 worker + Beat (self-hosted) **or** the `run_scheduled_tasks` management command (PythonAnywhere) |
| PDF parsing | pdfplumber 0.11.10 + pypdf 6.15.0 |
| Forms / admin | django-crispy-forms 2.7, crispy-bootstrap5, django-admin-interface |
| Production server | Gunicorn 26.0.0 (self-hosted); PythonAnywhere's WSGI server otherwise |

## 🚢 Deployment

The same code base runs on two targets, selected by
`DJANGO_DEPLOYMENT_TARGET` in `.env`:

| Target | Use when | Database | Reminders |
|---|---|---|---|
| `self_hosted` | You run your own Linux box with MySQL and Redis | MySQL or PostgreSQL | Celery worker + Beat |
| `pythonanywhere` | You're on a managed host (free tier supported) | SQLite | `run_scheduled_tasks` from a scheduled task |

### Production deployment runbook

📘 [docs/PRODUCTION_DEPLOYMENT.md](docs/PRODUCTION_DEPLOYMENT.md) — the
self-hosted MySQL / Redis / Gunicorn / Celery deployment process.

### PythonAnywhere deployment

🐍 [docs/PYTHONANYWHERE_DEPLOYMENT.md](docs/PYTHONANYWHERE_DEPLOYMENT.md) —
the step-by-step walkthrough for PythonAnywhere (free or paid), including
web app configuration, scheduled tasks, and the SQLite backup command.

### Self-hosted infrastructure analysis

🖥️ [docs/SELF_HOSTED_INFRASTRUCTURE.md](docs/SELF_HOSTED_INFRASTRUCTURE.md) —
what the app actually needs at scale, and a comparison of the PythonAnywhere
managed target versus a self-hosted box.

## 📚 Documentation

| Doc | Purpose |
|---|---|
| [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) | Launch-truth document — what is implemented vs. what still needs owner/operator action |
| [docs/AUTHENTICATION.md](docs/AUTHENTICATION.md) | Current account security model and the future Microsoft Entra plan |
| [docs/PRODUCTION_DEPLOYMENT.md](docs/PRODUCTION_DEPLOYMENT.md) | Self-hosted launch runbook |
| [docs/PYTHONANYWHERE_DEPLOYMENT.md](docs/PYTHONANYWHERE_DEPLOYMENT.md) | PythonAnywhere launch runbook |
| [docs/SELF_HOSTED_INFRASTRUCTURE.md](docs/SELF_HOSTED_INFRASTRUCTURE.md) | Hardware sizing and architecture analysis |
| [PROGRESS.md](PROGRESS.md) | Internal project progress and migration history |

## 📋 Project status

The codebase has a production-shaped, security-hardened foundation and a
131-test regression suite. The P0 launch-gate items in
[docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) — credential rotation,
restore proof, real SMTP acceptance, and signed user acceptance — are
owner/operator actions that this workspace cannot perform. The
remaining work does not require source-code changes; it requires
provisioning the production platform and walking through the
acceptance checklist.

Recent milestones:

- **2026-08-28** — PythonAnywhere deployment target: optional Celery/Redis,
  `run_scheduled_tasks` command, target-aware production check.
  131-test suite green.
- **2026-08-22** — Local-DB cleanup, dependency modernisation to
  Django 5.2 LTS, 121-test regression suite green.
- **2026-08-12** — Vehicle lifecycle, retirement, custody ledger, company
  locations, email alerts, controlled devices, searchable tool catalogue.
- **2026-08-11** — TOTP 2FA, recovery codes, public registration closed,
  role-scoped filter choices, dependency upgrade.

The full internal progress record — completed stabilization work,
required next steps, and per-migration SHA-256-verified backup history —
lives in [PROGRESS.md](PROGRESS.md).

## 🔐 Account security

After signing in, open **Security** and activate an authenticator app.
Scan the QR code, enter the current six-digit code, then download and
store the recovery codes separately from the device. Admin and Manager
accounts cannot use operational pages until enrollment is complete.
Standard users may opt in. See
[docs/AUTHENTICATION.md](docs/AUTHENTICATION.md) for recovery procedures
and the future Microsoft Entra plan.

## 🤝 Contributing

1. Discuss the change before opening a pull request.
2. Add a regression test with every defect repair.
3. Keep security, access control, and data integrity ahead of new features.
4. Never commit real credentials, databases, invoices, exports, or
   personal information.
5. Back up data before migrations or cleanup operations.
6. Update [docs/KNOWN_ISSUES.md](docs/KNOWN_ISSUES.md) when something
   changes.

## 📄 License

Proprietary. © Koinonia Enterprises. All rights reserved.
