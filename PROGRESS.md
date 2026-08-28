# Koinonia Asset Tracker — Internal progress record

> **This is the internal working recovery plan and progress record.**
> The public-facing README lives at [README.md](README.md). This file
> preserves the detailed project history, status, and migration
> provenance for operators and future maintainers.

This document was last updated on 22 August 2026 and is preserved
verbatim from the previous public README.

Launch documents: [Production gaps and known limitations](docs/KNOWN_ISSUES.md) · [Production deployment runbook](docs/PRODUCTION_DEPLOYMENT.md) · [PythonAnywhere deployment](docs/PYTHONANYWHERE_DEPLOYMENT.md) · [Authentication and future Entra plan](docs/AUTHENTICATION.md)

## Primary Goal

The end goal is a secure, reliable, production-ready asset management application that Koinonia can confidently use for daily company operations.

Every decision and work item must support that goal. Security, data integrity, account protection, essential business workflows, backups, testing, and operational reliability take priority over optional features. The project is not complete merely because pages render or individual features work; it is complete only when the application is safe to deploy, dependable with real company data, understandable to its users, and supported by tested backup and recovery procedures.

### Current highest priority

The current implementation order is:

1. Close the external launch gate: rotate exposed historical credentials, finish real-mail acceptance, prove a restore, and complete company-data review and signed user acceptance for Admin, Manager, and User roles. The deployment platform (PythonAnywhere managed host or self-hosted MySQL/Redis/Gunicorn) is now code-selectable via `DJANGO_DEPLOYMENT_TARGET`; both paths share the same code base and test suite.
2. Finish the Tool disposal/history/documents/repair workflow required before a broad rollout.
3. Expand supplier-specific PDF parsing and the remaining accident-update coverage.
4. Keep Entra login, Teams messages, tires, and further cosmetic work behind the production launch priorities.

Company Locations, Email Alerts/delivery history, controlled devices, the maintenance workspace, special vehicle maintenance, and QR fuel/odometer monitoring are implemented. They must not regress while the external launch gate is closed.

The PythonAnywhere deployment target (managed host, no Celery/Redis, SQLite, scheduled reminder command) was added on 28 August 2026. The self-hosted target keeps the original MySQL/Redis/Celery requirements and is now exercised by the same 131-test regression suite.

The post-2FA redirect, public registration, role-scoped filter choices, dependency upgrade, full regression suite, and isolated GUI role checks were completed on 11 August 2026.

## Product Scope

### Essential

- Admin, Manager, and User access levels
- Role-specific dashboards and data visibility
- Tool and vehicle inventory
- Assignments and transfers
- Odometer and service tracking
- Maintenance records, documents, line items, and costs
- User administration and password resets
- Registration, calibration, maintenance, and odometer reminders
- Fleet analytics and downloadable reports
- PDF maintenance-invoice parsing and import
- Accident and insurance records
- QR-guided weekly odometer and fuel-receipt tracking

### Optional later work

- Tire history, status, and reminders

## Current Status

The codebase now has a production-shaped, security-hardened foundation and a 131-test regression suite. It is not yet approved for company production because external credential rotation, real SMTP acceptance, restore proof, and company user acceptance cannot be completed inside this development workspace.

| Area | Status | Notes |
|---|---|---|
| Navigation | Repaired | Legacy route names and the missing maintenance deletion page were corrected. |
| Roles and permissions | Improved | Core inventory actions enforce Admin/Manager/User responsibilities, object ownership, and role-scoped filter choices. |
| User administration | Repaired | New users receive a password, role, and state; administrators reset the intended user's password. |
| Account security | Improved | Authenticator-app 2FA and recovery codes are available to all accounts; Admin and Manager enrollment is required, pending enrollment QR codes remain stable across refreshes, successful challenges reach the correct dashboard, public registration is closed, and the complete Security experience now matches the application on desktop and mobile. |
| Dependencies | Repaired | The supported Django 5.2 LTS stack is pinned, retired PyPDF2 was replaced, unused packages were removed, and the current audit reports no known dependency vulnerabilities. |
| NSW manager visibility | Repaired | NSW subdivisions now map to NSW vehicle and tool records. |
| CSV/Excel imports | Improved | Tool imports persist, file type/size/row limits are validated, and failed files roll back completely. |
| Vehicle lifecycle | Implemented and GUI-verified | Active, Sold, and Written off states, financial retirement details, Vehicle History, retained records, retirement checklist, role scoping, and tracked reminder email routing are implemented. |
| Transfers | Custody ledger implemented and GUI-verified | Admin-only source-first transfers support multiple/all tools, one vehicle, real company locations, immutable per-asset ledger entries, reversals, and cross-state follow-up tasks/emails. Legacy transfer rows remain preserved. |
| Company locations | Implemented and GUI-verified | Offices and Warehouses are real custody entities with role-scoped lists, profiles, filters, responsible managers, current assets, transfer history, and guarded deactivation in migration `0012`. |
| Email alert foundation | Implemented and GUI-verified | Admin-only mailbox configuration, responsibility/category routing, one primary State Manager per state, audited changes, delivery history, deduplication, failure recording, and safe retry are implemented. Service, odometer, retirement, transfer, special-maintenance, and follow-up events use tracked delivery; real SMTP acceptance remains required. |
| Controlled devices and catalogue | Profile foundation implemented and GUI-verified | Admin-only controlled classification, condition, replacement value, photo, employee/location custody, calibration requirements, validation, filters, badges, searchable catalogue selection, reviewed catalogue management, safe handling suggestions, role-scoped Tool profiles, calibration status, and immutable movement history are implemented. Tool lifecycle/history tabs, documents, maintenance records, and movement email triggers remain next. |
| Maintenance workspace | Implemented and GUI-verified | The filtered overview, profiles, protected documents, vehicle drill-down, special date/odometer requirements, upcoming/overdue states, recurrence, completion evidence, and tracked reminders are implemented. |
| Vehicle service state | Improved | A regular service advances current, last-service, and next-service odometer values. |
| PDF auto-create | Repaired | New vehicles use current model fields and parsed brake/tire work maps to a valid repair type. |
| PDF invoice GUI | Essential workflow complete; supplier expansion in progress | Admins and Managers can securely upload, preview, validate, explicitly confirm, and transactionally save a PDF invoice with its original document. The first real-layout MechanicDesk parser slice is modularized and covered by anonymized regression data; other supplier formats still need approved samples. |
| Calibration reminders | Repaired at code level | Correct tool names and recipient checks are used; production delivery still needs configuration. |
| Accident tracking | Improved and validated | Costs cannot be negative, future accidents and inconsistent insurance details are rejected, standard users are recorded as the driver, and filtered totals are visible. Company-example sign-off and update-flow coverage remain. |
| Analytics and reports | Validated with synthetic examples | Dashboard and exports use calendar month/year periods through today, exclude future records, honor the selected vehicle, and separate maintenance and accident costs. Approved company examples and performance testing remain. |
| Fuel and odometer monitoring | Implemented and GUI-verified | Printable revocable vehicle QR tokens open the exact active vehicle after login. Seven-day accepted readings, mandatory auto-rotated/compressed fuel receipts, suspicious-reading evidence/review, custody preservation, dashboards, and tracked reminders are implemented in migration `0016`. |
| Tires | Deferred | Tire tracking remains optional and must not delay the approved vehicle monitoring work. |
| PythonAnywhere deployment | Implemented and code-verified | The `DJANGO_DEPLOYMENT_TARGET=pythonanywhere` switch turns off Celery/Redis requirements, accepts SQLite + the local-memory cache, defaults the security headers to safe values, and exposes the `run_scheduled_tasks` management command for a PythonAnywhere scheduled task. The self-hosted target keeps the original MySQL/Redis/Celery requirements; both targets share the same 131-test regression suite. |

## Completed Stabilization Work

### Configuration and data safeguards

- Removed committed live-looking credentials from the active settings file.
- Added environment-based secrets, host, timezone, email, and security settings.
- Added `.env.example` without real credentials.
- Defaulted development email to console output to prevent accidental delivery.
- Added ignore rules to reduce new commits of databases, backups, invoices, uploads, bytecode, and local environment files.
- Preserved all existing databases, invoices, exports, backups, and user changes.
- Created and hash-verified a database backup before applying transfer migration `0007`.

### Account security

- Added authenticator-app two-factor authentication (TOTP).
- Added recovery-code viewing, downloading, and regeneration.
- Required Admin and Manager accounts to enroll before accessing operational pages.
- Kept 2FA optional and available for standard User accounts; add `User` to `DJANGO_MFA_REQUIRED_ROLES` to require it for everyone.
- Routed password login through the account system's MFA-aware login stages.
- Added a Security link to the signed-in navigation.
- Corrected the successful 2FA handoff so Admin and Manager accounts reach their proper dashboards.
- Stabilized the pending authenticator secret within the signed-in session so refreshing or revisiting the activation page does not invalidate a QR code that was already scanned.
- Replaced the inconsistent built-in 2FA screens with responsive, company-branded Security, enrollment, challenge, recovery-code, reauthentication, trust, and deactivation pages.
- Closed anonymous self-registration; company accounts remain administrator-created.
- Recorded a future Microsoft Entra sign-in plan in `docs/AUTHENTICATION.md`; Entra is not enabled until tenant and application decisions are confirmed.

### Import safety

- Limited imports to matching `.csv` or `.xlsx` files no larger than 5 MB.
- Rejected empty files, duplicate columns, and files over 5,000 rows.
- Added required-column and required-value checks with supported role, state, and tool-name validation.
- Wrapped each complete import in one database transaction so a failed row rolls back the entire file.
- Replaced raw unexpected exception details with a controlled operator message while retaining server-side logging.

### Navigation and user management

- Corrected all known legacy template route names.
- Removed the duplicate car odometer route.
- Added the missing maintenance deletion confirmation template.
- Restored proper user creation with password, role, and state fields.
- Replaced the misleading password-change route with an administrator-controlled target-user password reset.
- Ensured legacy/imported users receive a profile safely.

### Visual design and usability

- Introduced a shared professional design system for typography, colour, spacing, cards, buttons, forms, tables, badges, alerts, and empty states.
- Rebuilt the signed-in navigation with a responsive company-branded application shell and clearer section icons.
- Modernized the Admin, Manager, and User dashboards plus vehicles, tools, maintenance, accidents, analytics, user management, and core add/edit forms.
- Replaced the legacy login screen with a company-branded responsive sign-in experience consistent with the 2FA screens.
- Added contained horizontal scrolling for wide operational tables instead of allowing mobile page overflow.
- Verified the dashboard, vehicles, analytics, login, and data-entry form layouts at desktop and 390-pixel mobile widths with no browser-console warnings or errors.

### Permissions

- Administrators and managers can create and edit tools, cars, and maintenance records.
- Destructive tool, car, and maintenance actions require an administrator.
- Managers are restricted to their state.
- Regular users are restricted to their assigned cars, odometer records, and accidents.
- Accident deletion requires a manager or administrator.
- Restricted actions return a forbidden response instead of redirecting authenticated users to login.
- Restricted tool, vehicle, maintenance, accident, and analytics filter choices to the same fleet scope as their page results.
- Removed the unusable Manager delete action and corrected assigned-user labels to fall back to usernames.

### Business workflows

- Tool CSV uploads now persist data.
- Tool transfers now accept string internal numbers such as `KE-01`.
- Maintenance-item totals now use compatible decimal arithmetic.
- Maintenance line-item edits and deletions now use the complete formset save process inside a transaction.
- Regular servicing now advances the vehicle's service odometer.
- PDF vehicle auto-creation no longer uses a removed field.
- PDF brake and tire work maps to the supported `repair` service type.
- Calibration reminders use `tool_name` and skip unusable recipient addresses.
- Fleet analytics now show maintenance, accident, and recorded total costs using one calendar-based rule through the current day.
- Monthly and yearly exports use the same date and vehicle filters as the dashboard and reject unsupported report requests.
- Fuel analytics stay hidden when there is no fuel data and remain clearly marked as optional when present.
- Accident forms reject future dates, negative company costs, and contradictory insurance information.
- Standard users are automatically recorded as the driver on accident records, while NSW managers can select drivers from either NSW subdivision.
- Added a focused parser registry and shared invoice data types so supplier formats can move out of the legacy 3,300-line parser incrementally without changing its public interface.
- Added an anonymized MechanicDesk-layout regression fixture derived from an existing local invoice's structure without copying company, supplier, contact, vehicle, or invoice identifiers.
- Repaired MechanicDesk extraction of supplier name, odometer, and decimal-quantity labour lines while retaining invoice number, registration, subtotal, GST, and final-total accuracy.
- Corrected PDF preview validation so pre-tax line items are compared with the subtotal instead of incorrectly being compared with the tax-inclusive total.
- Added a `DJANGO_DEPLOYMENT_TARGET` switch so the same code base runs on PythonAnywhere (no Celery, no Redis, SQLite + local-memory cache, scheduled reminder command) or on the self-hosted MySQL/Redis/Gunicorn stack; the production check, security defaults, and PyMySQL import are all target-aware.
- Added the `run_scheduled_tasks` management command so registration, maintenance, calibration, retirement, transfer follow-up, special-maintenance, and weekly-odometer reminders keep running from a PythonAnywhere scheduled task when Celery Beat is unavailable.

### Dependency modernization

- Upgraded Django from 5.0.6 to the supported and security-patched 5.2.17 LTS release.
- Upgraded django-allauth from 0.63.3 to 65.19.0 and retained authenticator-app MFA and recovery codes.
- Upgraded Pillow to 12.3.0, PyMySQL to 1.2.0, and Gunicorn to 26.0.0.
- Upgraded the configured form and administration packages to Django 5.2-compatible releases.
- Replaced retired PyPDF2 with maintained `pypdf` 6.15.0 and updated both invoice parser implementations.
- Pinned pdfplumber 0.11.10 for repeatable invoice parsing.
- Removed unused runtime declarations for django-environ, django-celery-beat, WhiteNoise, python-dotenv, django-ses, Sentry SDK, Django REST Framework, and django-cors-headers.
- Removed unused development/test declarations for django-debug-toolbar, django-extensions, pytest, pytest-django, and factory-boy. Tests continue to run through Django's built-in test runner.
- Removed direct python-dateutil and pytz declarations; pandas installs the compatible versions it requires.

### Tests and GUI verification

The project now has 131 passing tests covering:

- Current route names
- Manager dashboard rendering
- Maintenance deletion confirmation
- User creation, roles, states, and passwords
- Target-user password reset
- Core access restrictions
- Odometer and accident ownership
- Tool CSV import
- String-keyed tool transfers
- Decimal maintenance totals
- Maintenance line-item deletion
- Vehicle service-state updates
- PDF vehicle auto-creation and service classification
- Calibration reminder delivery
- Mandatory 2FA enrollment for privileged accounts
- Optional 2FA access for standard users
- Access after enrollment
- Second-factor challenge after password login
- Import extension/format validation
- Complete import rollback when a later row is invalid
- Successful Admin and Manager 2FA completion through to the correct dashboard
- Real password-login activation that preserves the pending QR secret after refresh and invalid submissions
- Successful activation saving the authenticator before redirecting
- Closed anonymous registration by both GET and POST
- Role-scoped filter choices for tools, cars, maintenance, accidents, and analytics
- Username fallbacks and Manager action visibility
- Legacy car-import warnings for invalid optional purchase data
- Legacy fallback driver matching
- Secure PDF file and pending-import integrity validation
- PDF preview without database writes
- Transactional PDF confirmation, duplicate blocking, document retention, and role/state restrictions
- Invoice subtotal, GST, and final-total separation
- Safe rendering of unassigned vehicles and tools
- Calendar year-to-date analytics with future records excluded
- Exact monthly CSV and yearly Excel maintenance and accident totals
- Vehicle-filtered report output and rejected invalid report requests
- Accident date, cost, insurance, driver, NSW visibility, and filtered-total rules
- An anonymized MechanicDesk invoice layout, including supplier, vehicle, odometer, decimal labour quantity, line items, subtotal, GST, total, and confidence values
- Company Location permissions, filtering, profiles, custody counts, validation, and safe deactivation
- Email Alert permissions, validation, primary-per-state routing, enabled/category recipient resolution, delivery deduplication, failure recording, and Admin retry
- Controlled-device legacy-safe defaults, evidence and calibration validation, exclusive employee/location custody, Admin-only classification, and list filtering/badges
- Searchable catalogue rendering, approved-name selection, legacy catalogue seeding, case/spacing duplicate prevention, inactive-item blocking, Admin-only management, and audited catalogue creation
- Role-scoped Tool profiles, controlled-device identity, employee/location custody, calibration status, and immutable movement-ledger display
- Reminder batch failure isolation, scheduled-maintenance query scaling, registration/calibration templates, pagination/filter preservation, and whole-result accident totals
- Role-scoped Maintenance profiles, full filtered-workspace summaries, vehicle drill-down links, compact vehicle maintenance summaries, and flat list queries with line items
- Flat-query fleet report generation and single-query per-car fuel-efficiency calculations, including a correct previous-reading comparison
- PythonAnywhere deployment target accepts SQLite, the local-memory cache, and disabled Celery, while the self-hosted target still rejects each of them
- `run_scheduled_tasks` management command lists every registered reminder, runs only the requested task, skips missing tasks without aborting, and exits non-zero when a task crashes
- Deployment target flag is wired through both settings and the production check so `manage.py check --deploy` fails on the self-hosted target and only warns on the PythonAnywhere target

The tests use a disposable in-memory database and do not alter the operational SQLite database.

Isolated browser tests were completed against disposable migrated databases both before and after the dependency upgrade. Under Django 5.2 and django-allauth 65.19, Admin, Manager, and User login flows worked; Admin and Manager completed real authenticator-code challenges; core dashboards, lists, analytics, imports, security, and add forms rendered without server errors; a User created a disposable odometer reading and accident record; NSW accounts did not see VIC fleet data; and the browser console reported no warnings or errors.

The operational Admin enrollment flow was rechecked after a report that entering a code returned to a newly generated QR. The application had no saved Admin authenticator, proving enrollment had not completed. A regression test reproduced that a fresh activation-page GET changed the pending secret. The activation form now reuses one session-bound pending secret until successful enrollment clears it, and a GUI refresh confirmed the QR remains unchanged. The project now has a rebuilt `.venv` using the pinned Django 5.2.17 and django-allauth 65.19.0 stack; local runs must use this environment rather than global Python packages.

On 12 August 2026, the complete 2FA GUI was rechecked with a disposable account. The pending QR and manual setup key remained unchanged after refresh, a real generated authenticator code advanced to the recovery-code page, and the Security page then reported the authenticator as active. The branded sign-in challenge, Security overview, and activation page were visually checked at desktop and 390-pixel mobile widths with no horizontal overflow or browser-console warnings/errors. The disposable account and its related records were removed after testing.

On 13 August 2026, the optimization changes were checked against the signed-in operational GUI. Dashboard metrics rendered with current values; Tool Catalogue showed 50 rows per page and preserved `status=all` when moving to page 2; Users, Email Alerts, Vehicle History, and Fleet Analytics rendered normally. The dashboard, catalogue, users, and analytics pages were also checked at 390-pixel mobile width with no page overflow or browser-console errors.

The PDF invoice workflow was also exercised end to end in a disposable GUI environment with a real one-page sample: upload, preview, confidence and warning display, explicit confirmation, document attachment, success feedback, duplicate blocking, and mobile layout all worked without browser-console errors. This test exposed and fixed an unassigned-car dashboard crash, corrected subtotal/GST/total extraction, and reduced sample parsing time from several minutes to about 1.4 seconds by removing noisy third-party DEBUG logging.

A later disposable GUI run used a fully anonymized MechanicDesk-layout PDF and the real parser rather than a mocked result. It correctly previewed and saved the supplier, vehicle, 231,580 km odometer, 0.3-hour labour line, parts line, $321.40 subtotal, $32.14 GST, and $353.54 total without browser errors. This run exposed and fixed the false warning that previously compared pre-tax items with the tax-inclusive total. The ignored source invoice remained untouched and was not copied into the repository.

The latest analytics and accident GUI check used a disposable migrated database with exact sample totals: $150 maintenance, $35 accident cost, and $185 recorded fleet cost. The fuel card stayed hidden with no fuel records, the accident list showed the same $35 total, and invalid future, negative-cost, and incomplete-insurance submissions displayed the expected errors. A 390-pixel mobile check exposed horizontal overflow in the analytics export controls; the controls were changed to stack on narrow screens and the repeat measurement confirmed no page overflow.

### Security and production verification on 22 August 2026

- Pip-audit reports no known dependency vulnerabilities after upgrading Django to 5.2.17.
- Bandit reports no findings in deployable application code. Test-fixture passwords are excluded from the production-code result.
- Detect-secrets found only the clearly labelled development placeholder and test fixtures in current source; it did not identify a live production credential pattern.
- The isolated resolver reported no broken or conflicting requirements.
- Django's migration check reported no missing model migrations.
- The production-style deployment check reported no issues when all secure deployment values, including the final HSTS choices, were explicitly enabled. The real HSTS subdomain and preload policy must still be approved for the company domain.
- Static collection succeeds, liveness/readiness checks pass, and the rebuilt local environment has no broken requirements.
- The Windows backup command is regression-tested; pre/post-migration backups passed integrity and record-count checks.
- Desktop and 390-pixel GUI acceptance covered dashboards, cars, tools, maintenance, Service plans, odometer review, transfers, alerts, analytics, Security, vehicle profiles, printable QR labels, and the new entry forms with a clean fresh browser console.
- A GitGuardian full-history scan was not run because no approved GitGuardian account/API key is configured. Full-history secret scanning remains a CI requirement; the current-source equivalent was completed with detect-secrets.

### Optimization and operational audit on 22 August 2026

- [x] Operational databases, archives, exports, uploaded media, and bytecode were removed from Git tracking and their file classes were added to `.gitignore`. The files remain on disk and the database backup was hash-verified. These staged cleanup changes have not been committed.
- [x] All five scheduled-reminder tasks isolate each delivery failure, return sent/failed counts, log failures, and avoid the identified fleet-size N+1 patterns. Broken reminder templates were repaired and covered by tests.
- [x] Fleet Analytics vehicle-cost queries are now flat as fleet size grows: the measured real-fleet case remains at 42 queries rather than growing per vehicle.
- [x] Seven main operational lists are paginated at 50 records and preserve active filters. Previously unreachable Company Location and Delivery History pages now expose pagination controls. Accident totals aggregate over the complete filtered result rather than the current page.
- [x] The Maintenance workspace prefetches line items and has a query-scaling regression test, so adding records with line items does not add one query per row.
- [ ] **Production blocker:** broker/result/cache settings and all required schedules are defined through environment variables. Production still needs Redis, separate Celery worker and Beat services, restart/health monitoring, and controlled delivery testing. Tire reminders remain intentionally unscheduled while tires are deferred.
- [ ] **Security blocker:** the operational database appeared in pushed commits `6bdece5` and `b2bfbb4`. Rotate the four affected account passwords regardless of whether Git history is rewritten, then decide on coordinated history cleanup and full-history secret scanning.
- [x] `GenerateReportView` now bulk-aggregates maintenance, fuel, accidents, last service, and fuel efficiency. Its new scaling test confirms that adding vehicles does not add per-vehicle queries.
- [x] Car fuel efficiency now reads the required full-tank sequence once, calculates current/previous/average/best/worst values in memory, and avoids repeated predecessor lookups in dashboard and report loops.
- [x] Relationship N+1s were removed from the legacy notification helpers' whole-fleet and manager-profile loops. Routing those legacy events through the tracked notification service remains part of the end-to-end notification work.
- [x] Tool Catalogue, Vehicle History, Users, Email Alert contacts, and legacy role-specific car/tool lists are paginated at 50 records using the shared filter-preserving controls.
- [x] Dashboard template `.count` calls were replaced with explicit metrics, while vehicle rows are evaluated once and reused for their count and display.
- [ ] Review indexes with production query plans after special-maintenance and lifecycle fields are final. Likely composite candidates include maintenance `(car, service_date)`, accidents `(car, accident_date)`, fuel `(car, date)`, and notification delivery `(status, scheduled_at)`; do not add speculative indexes before measuring write/read tradeoffs.

## Required Next Work

### Agreed vehicle lifecycle, retirement, and custody work

Implementation progress as of 12 August 2026:

- [x] Vehicle lifecycle fields, safe retirement, Vehicle History, retained operational history, retirement checklist, permissions, and initial retirement email routing were implemented and migrated after a verified backup.
- [x] Admin-only source-first custody batches, multiple/all tool selection, one-vehicle enforcement, real warehouse custody, immutable asset ledger entries, reversals, and auditable cross-state registration tasks/email routing were implemented in migrations `0010`–`0011`, each applied after a verified backup.
- [x] Company Locations were implemented in migration `0012`: Offices/Warehouses/Inactive views, search and state/type filtering, Admin create/edit, Manager state-scoped visibility, location profiles, current assets, transfer history, responsible manager, and blocked deactivation while assets remain.
- [x] Email Alert contacts and notification delivery history were implemented in migration `0013`: Admin-only management, shared mailboxes without fake users, role/category routing, one primary State Manager per state, audit fields, deduplication, failure recording, and safe retry.
- [x] Controlled-device data and validation were implemented in migration `0014`: Admin-only classification, condition, replacement value, photograph, employee/location custody, calibration requirements, list badges and filters, and safe ordinary-tool defaults for every existing record.
- [x] Searchable tool catalogue selection and Admin catalogue management were implemented in migration `0015`: 146 approved/existing names, keyboard-searchable entry, controlled/calibration suggestions requiring confirmation, active/inactive control, duplicate prevention, audit fields, and import validation against the same catalogue.
- [x] The initial Tool profile was implemented with controlled-device identity, photo/condition badges, employee or Company Location custody, assigned vehicle, replacement value, calibration status, and immutable movement ledger. It is linked from Tools and Company Location profiles and respects Admin/Manager/User visibility.
- [x] The initial Maintenance workspace and profile were implemented without a schema migration: filtered whole-result metrics, service-type filtering, pagination, direct record profiles, vehicle/invoice/work/line-item/document summaries, and car-to-maintenance drill-down. Vehicle profiles now show lifetime maintenance cost and the five most recent linked records.
- [x] Complete signed-in GUI acceptance for the Company Location and Email Alert foundation screens, including responsive empty states, forms, filters, required-field validation, and delivery history.
- [x] Complete signed-in desktop/mobile GUI acceptance for core lifecycle, transfer, maintenance, Security, and monitoring screens.
- [x] Add tracked recurring reminders for incomplete retirement and transfer follow-up tasks.
- [x] Implement printable vehicle QR labels, exact-vehicle entry, seven-day odometer status, suspicious-reading evidence/review, mandatory auto-rotated/compressed fuel receipts, and escalation reminders.
- [x] Implement fleet-manager special maintenance requirements with date/odometer due rules, recurrence, completion evidence, status views, car-profile summary, and tracked reminders.

The following business rules were agreed on 12 August 2026 and must be preserved during implementation:

- Add vehicle statuses **In service** (default), **Sold**, and **Written off**.
- Do not mark a vehicle Written off until the insurer confirms the write-off. At retirement, both Sold and Written off vehicles must record the final amount received, payment date, payment source, reference, final odometer, retirement date, notes, and supporting documents. Written off uses the insurance settlement as the final value.
- Remove Sold and Written off vehicles from operational dashboards, assignments, reminders, forms, imports, active fleet lists, and active service calculations without deleting any historical maintenance, invoice, accident, odometer, transfer, or cost records.
- Keep **Vehicle History** inside the Cars section as an Active Vehicles / Vehicle History view; do not add another top-level navigation item.
- Create a read-only historical vehicle profile with identification, retirement details, final value, documents, maintenance, invoices, accidents, odometer history, assignments, transfers, and lifetime recorded cost.
- When a vehicle is retired, unassign its driver and tools and create a tracked fleet-retirement checklist for registration refund, CTP refund, NRMA removal, insurance removal, fuel card, toll tag, tracking equipment, company equipment recovery, documents, and final payment confirmation.
- Email the configured fleet manager and responsible state manager when retirement starts, remind them about incomplete checklist items, and stop reminders only when the checklist is complete. Preserve completion user and timestamp for every task. A future Teams notification may complement email.
- Replace ordinary vehicle deletion with retirement. Reserve permanent deletion for an erroneous duplicate with no related history, using an explicit Admin-only safeguard. Keep registration and VIN values reserved in history.

The transfer workflow will become an Admin-only, guided custody workflow:

- Select the source person or **Unassigned/Warehouse** first, then show only the active vehicles and tools currently held there. Never require an operator to type a raw item ID.
- Allow one transfer to include multiple tools, all tools held by the source, and at most one vehicle because each employee can hold only one active vehicle.
- Show friendly asset descriptions with codes as secondary reference, support search/filtering, exclude historical vehicles, select the destination after the assets, and present a complete review before confirmation.
- Treat Warehouse as a real custody location rather than a fake user account.
- Record every custody movement in an immutable transfer ledger. Keep current assignment fields for fast operational use, but never edit or delete ledger history; correct errors with a reversal transaction linked to the original.
- Use one batch transfer header with individual asset ledger entries so the complete movement succeeds or fails together and every tool remains independently traceable.
- When a vehicle moves between states, create tasks and send email to the fleet manager and both relevant state managers to complete the registration/state change. Preserve registration history rather than overwriting the only record of the previous registration.
- Email affected people when a transfer completes. A future Teams message should state who transferred assets to whom and list the included vehicle/tools.

### Agreed tools, controlled devices, company locations, maintenance, and email work

The following requirements were agreed on 12 August 2026 and are the next approved implementation plan.

#### Tool and controlled-device model

- Keep ordinary tools and valuable specialist devices in the same Tool system. Do not create a separate device inventory that would split custody and transfer history.
- Add a **Controlled device** checkbox for scarce, important, or high-value equipment such as PIM testers, OTDRs, splicers, and other specialist test instruments that can cost tens of thousands of dollars.
- Keep estimated replacement value, but do not use price alone to determine control. An Admin must be able to mark a rare shared device as controlled even when its value is missing or below a suggested threshold.
- For a controlled device, require an internal number, serial number, device type, photograph, current condition, and current employee or company location. Require calibration details when the device type needs calibration.
- Continue using the existing transfer ledger for all tools. Ordinary tools such as drills, wrenches, power tools, and tool bags do not need an email for every movement, but their custody changes must still be recorded.
- Treat every movement of a controlled device as a reportable event, including employee-to-employee, employee-to-location, location-to-employee, and location-to-location movements within the same state.
- Controlled-device transfer records must prominently show the device name, with its internal number and serial number as supporting identifiers.
- Add recipient acknowledgement for controlled-device handovers as a later enhancement after the notification and custody workflow is stable.

#### Controlled-device transfer notifications

- Every controlled-device movement sends an alert, even when the origin and destination are in the same state.
- A same-state controlled-device movement alerts the configured Fleet Manager mailbox and the configured State Manager mailbox for that state.
- A cross-state controlled-device movement alerts the Fleet Manager plus exactly **two State Managers total**: one responsible State Manager for the origin state and one responsible State Manager for the destination state.
- Project Managers are the existing State Managers; do not create another application role or contact class for Project Manager.
- Admin Alert mailboxes may receive controlled-device alerts when enabled for that alert category. Do not automatically email every Admin account.
- Alerts must identify the device, serial/internal numbers, origin holder/location, destination holder/location, states, transfer operator, and transfer time.
- Email delivery must never replace the immutable ledger. A failed email leaves the completed transfer recorded and creates a visible retry/failure item.

#### Searchable tool creation and tool views

- Replace the very large tool-name dropdown with an autocomplete search field backed by the approved tool catalogue. It must support keyboard use and fast matching for terms such as PIM, OTDR, drill, tester, and tool bag.
- Do not use unrestricted free text for normal creation because spelling variations would create duplicate tool types. Allow an Admin to add a new catalogue item through an explicit reviewed action when no match exists.
- Catalogue entries may suggest defaults such as Controlled device and Calibration required, but the Admin confirms them before saving.
- Add a car-style Tool profile showing photo, identity, device type/category, controlled status, replacement value, condition, current custodian/location, state, calibration, documents, repair history, and complete movement ledger.
- Add Active Tools and Tool History views inside the Tools section. Proposed lifecycle values are Active, Lost, Damaged, Sold, and Retired; final disposal rules must be reviewed before implementation.
- Keep controlled devices visually distinguishable in lists, profiles, searches, and transfer selection.
- Build the Tools section to match the useful Cars pattern: searchable/filterable Active Tools list, Tool History tab, Add Tool action, individual Tool profile, Edit action, controlled status, custody details, maintenance/calibration history, documents, and movement ledger.
- The Tool profile must show pending actions and overdue calibration prominently instead of requiring the operator to search separate reports.

#### Offices and warehouses

- Treat offices and warehouses as company custody locations, never as fake users.
- Generalize the existing Warehouse entity to a **Company Location** with type Office or Warehouse, name, state, address, active status, and responsible State Manager contact.
- A location can hold ordinary tools and controlled devices. Office is the normal location for valuable specialist devices; Warehouse is the normal location for ordinary field tools, but these are defaults rather than hard restrictions.
- Allow employee-to-location, location-to-employee, and location-to-location transfers without losing the individual asset ledger.
- This requirement is about individually tracked tools and devices, not quantity-based consumables such as screws. A separate stock/consumables module is not part of the current scope.
- Add a full **Company Locations** interface within the Tools/Transfers area, not merely database records. It will include All, Offices, Warehouses, and Inactive views; Add/Edit Location actions; search and state/type filters; and a location profile.
- The Company Location profile will show its name, type, address, state, responsible contact, ordinary tools, controlled devices, pending calibration/maintenance actions, inbound/outbound transfers, and full custody history.
- Deactivating a location must be blocked while it still holds assets. Assets must first be transferred to a person or another active location so custody history remains accurate.
- Company Locations will not initially become a separate top-level navigation item. They will be reachable from Tools and Transfers to keep the main navigation focused; this can be revisited after GUI testing.

#### Vehicle service and special-maintenance requirements

- Keep normal vehicle service reminders based on the current service date and odometer rules.
- Add fleet-manager-controlled special maintenance requirements instead of adding more vehicle statuses. Examples include timing belt, major service, transmission service, brake inspection, battery replacement, and registration inspection.
- Each special requirement supports a vehicle, title/type, due date, due odometer, advance reminder period/distance, recurrence where applicable, notes, completion record, completed odometer, documents, and completion user/time.
- A vehicle may have several active special requirements at the same time.
- Improve the Maintenance section with Upcoming, Overdue, Special Requirements, Completed History, and Pending Invoice Review views.
- Add a maintenance detail/profile view with service information, line items, costs, documents, reminders, and audit history.
- Build a Maintenance workspace comparable in quality to Cars: an overview dashboard, searchable/filterable records, clear status tabs, Add Maintenance and Add Special Requirement actions, and individual maintenance record/detail pages.
- From a vehicle profile, provide direct access to that vehicle's complete maintenance history and active special requirements. From a maintenance record, provide a direct link back to the vehicle profile.

#### Configurable alert mailboxes

- Add an Admin-only **Email Alerts** configuration area inside Users/Security.
- Alert contacts may be shared mailboxes and do not need fake application user accounts.
- Each contact stores mailbox name, email address, responsibility type, optional state, enabled status, and selected alert categories. It may optionally link to a real application user.
- Supported responsibility types initially are Fleet Manager, State Manager, and Admin Alerts. There is no separate Project Manager type.
- Allow multiple configured contacts, but require one clearly designated primary State Manager per state for controlled-device routing so the cross-state rule always resolves to exactly one origin and one destination State Manager.
- Validate email addresses, prevent ambiguous duplicate primary contacts, record who changed notification settings, and never expose configuration to Managers or standard Users.

The initial email routing matrix is:

| Event | Required recipients |
|---|---|
| Normal vehicle service approaching or overdue | Vehicle custodian and configured Fleet Manager |
| Fleet-manager-entered special maintenance | Configured Fleet Manager; add custodian only when enabled for the requirement |
| Tool calibration approaching | Current tool holder and responsible State Manager |
| Tool calibration overdue | Current tool holder, responsible State Manager, and Fleet Manager |
| Vehicle confirmed Written off | Fleet Manager, vehicle-state State Manager, and enabled Admin Alerts |
| Controlled device moved within one state | Fleet Manager and that state's primary State Manager |
| Controlled device moved between states | Fleet Manager, one origin State Manager, and one destination State Manager; enabled Admin Alerts are optional |
| Ordinary tool movement | Ledger only; no automatic movement email |

#### Notification reliability and acceptance tests

- Use one notification service and one delivery-history model for service, special maintenance, calibration, Written off, retirement-checklist, transfer, and future odometer reminders.
- Record event type, related object, recipients, subject, scheduled time, sent time, status, attempt count, failure reason, and deduplication key.
- Prevent duplicate reminders for the same event and reminder window while allowing deliberate retries after failure.
- Email failure must not roll back a valid retirement, maintenance update, or transfer. Show failures to Admins and support safe retry.
- Test the real configured email provider first with approved test mailboxes before enabling scheduled delivery to employees.
- Automated tests must verify correct recipients, absence of unrelated recipients, same-state and cross-state routing, exactly two State Managers for cross-state controlled-device moves, controlled versus ordinary tools, upcoming versus overdue reminders, disabled contacts, deduplication, retries, and failure recording.
- GUI tests must cover Email Alerts configuration, searchable tool creation, controlled-device badges/profiles, tool and maintenance views, source-first transfers, special-maintenance creation, and notification-history/failure screens.
- Production acceptance must include a controlled test for normal service, special maintenance, calibration, Written off, same-state controlled-device transfer, and cross-state controlled-device transfer. Test messages must be clearly labelled and must not be sent to real employees without approval.

#### Approved implementation order

1. [Complete] Add Company Locations, their list/profile/manage screens, and migrate existing warehouses without losing custody references.
2. [Complete] Add Email Alert contacts, primary-per-state validation, audit fields, notification delivery history, and safe retry/deduplication.
3. [Complete] Add controlled-device fields and validation to Tool while preserving every existing tool record.
4. [Complete] Replace the tool-name dropdown with catalogue autocomplete and an Admin-controlled catalogue-add workflow.
5. [Partly complete] Tool profiles, filters, custody, calibration, controlled-device handling, and movement history work. Tool disposal/history, documents, and repairs remain.
6. [Complete except deferred acknowledgement] Controlled-device and cross-state transfer notifications use audited delivery; recipient acknowledgement remains optional later work.
7. [Complete] Special vehicle maintenance and the Maintenance overview/list/detail workspace are implemented.
8. [Code complete; external acceptance pending] Required events use reliable delivery paths, but the approved real SMTP/mailbox matrix must be tested before Beat is enabled.
9. [Complete locally] Migrations `0016`–`0017`, verified backups, 121 automated tests, and signed-in desktop/mobile GUI regression are complete.

Microsoft Entra sign-in remains an approved future option alongside local login. The intended model is single-tenant Microsoft sign-in, Entra MFA for Microsoft sessions, application TOTP for local sessions, minimal local emergency Admin accounts, explicit Admin/Manager/User role mapping, state assignment for Managers, safe account linking, offboarding, and a staged User-then-Manager-then-Admin pilot.

The approved driver monitoring and fuel workflow is:

- Separate the long-term **vehicle custodian** from the temporary driver. Daily vehicle use must not force the fleet manager to transfer custody.
- Give every active vehicle a random, revocable QR identifier. An authenticated employee scans the physical vehicle QR to open that exact vehicle; employees must not browse or select arbitrary fleet vehicles.
- Display the vehicle photo, registration, make, and model prominently and require confirmation before a fuel or odometer submission. Record the submitting employee, vehicle, date/time, source QR, and effective custody/usage context in the audit history.
- QR access permits activity entry for that vehicle but does not change its custodian. Admin-controlled custody transfers remain separate.
- Make the regular odometer reading due seven days after the latest accepted reading rather than on a fixed weekday. A valid odometer entered with a fuel purchase satisfies the weekly requirement.
- Reject decreasing odometer values except through a documented Admin correction such as an odometer replacement. Flag a reading for review when it exceeds 3,000 km in seven days, exceeds 1,000 km within 24 hours, conflicts with recent entries, or the vehicle is already flagged.
- Require a dashboard photograph only for suspicious readings. Suspicious submissions remain Pending review and must not update service calculations until the fleet manager accepts them.
- Require a fuel receipt photograph for every fuel entry. Automatically correct rotation, resize and compress oversized images while keeping receipt text readable; validate type/size and retain receipts in managed production file/object storage under the company financial retention and backup policy.
- Fuel entry must capture odometer, litres, amount paid, price per litre, station, receipt, and employee; validate reasonable values and flag duplicate or unusual transactions. Admin entry on behalf of an employee requires a reason.
- The User dashboard should show the official assigned vehicle, a recently QR-scanned vehicle when relevant, assigned tools, weekly reading status, service status, fuel entry, QR guidance, and outstanding correction/photo requests.
- The fleet view should show overdue readings, suspicious readings awaiting review, unassigned vehicles, recent QR activity, missing/invalid fuel receipts, duplicates/unusual fuel transactions, approaching services, state-change tasks, and retirement tasks.
- Send the first overdue-reading reminder to the official custodian and escalate to the fleet manager if it remains overdue. Do not remind employees without a current vehicle.
- Tire tracking remains deferred and must not delay this approved vehicle monitoring work.

### 1. Complete the production-readiness security batch

- [x] Fix the incorrect role destination after a successful 2FA challenge.
- [x] Disable public self-registration at `/accounts/signup/`.
- [x] Add regression tests for 2FA role redirects and blocked anonymous registration.
- [x] Upgrade from unsupported Django 5.0 to supported Django 5.2 LTS.
- [x] Upgrade or remove dependencies reported by the vulnerability audit.
- [x] Replace retired PyPDF2 with maintained `pypdf` and retest the parser-backed workflows.
- [x] Correct fleet-wide filter choices that reveal data outside the signed-in user's role or state.
- [x] Resolve the low-severity silent exception handlers reported by static analysis and add regression coverage.
- [x] Rerun dependency auditing, static security analysis, secret detection, all tests, and full GUI role checks after the changes.
- Configure GitGuardian or an equivalent full-history scanner in CI when an approved account and API key are available.

### 2. Complete external security actions

These actions cannot be completed safely by editing source code alone:

1. Rotate the Django secret and every database/email credential that has appeared in the repository.
2. Confirm whether committed databases, invoices, exports, backups, and photos contain sensitive information.
3. Back up operational records outside the source repository.
4. Decide whether shared Git history can be cleaned without disrupting other users.
5. Never delete or rewrite operational data without a verified backup and explicit approval.

### 3. Validate and strengthen imports

- Add a dry-run preview and explicit confirmation before writing.
- Expand row-level validation for every optional car, tool, and user field.
- Add downloadable error reports for rejected files.
- Consolidate overlapping car and maintenance import commands.
- [x] Add preview and confirmation before saving PDF-extracted information.

### 4. Complete PDF invoice reliability and GUI workflow

- [x] Add a secure PDF upload page accessible only to authorized roles.
- [x] Show extracted invoice, supplier, vehicle, date, odometer, line-item, tax, and total information before saving.
- [x] Require explicit confirmation and make the final save transactional.
- [x] Add the first anonymized real-layout fixture for the MechanicDesk format.
- Obtain approved, anonymized samples for every other supported supplier; do not infer full supplier support from synthetic text alone.
- [x] Add initial regression tests for invoice number, supplier, vehicle, date, odometer, items, tax, and total; repeat with every supported supplier sample.
- [x] Record extraction confidence and require confirmation for uncertain values.
- [x] Establish shared parser types and a focused format registry, then extract the first independent MechanicDesk parser.
- Continue moving supplier parsers into independent modules only after each format has regression coverage.
- The legacy `pdf_invoice_parser-tgm.py` was compared against the active parser on the available local invoice and did not preserve any superior result; formally archive or remove it in a separately reviewed cleanup.

### 5. Validate analytics and accidents

- [x] Confirm maintenance and accident totals against controlled synthetic examples.
- Confirm the same totals against approved company examples and record business-owner sign-off.
- [x] Verify calendar monthly CSV and yearly Excel reports with exact automated totals and vehicle filtering.
- Add the remaining accident-update regression coverage; creation, dates, insurance fields, costs, drivers, visibility, and filtered totals are covered.
- Optimize repeated per-vehicle calculations only after correctness is proven.
- [x] Keep fuel sections hidden when no supporting data exists and clearly optional when present.

### 6. Complete notifications

- Configure the real email provider through environment variables.
- Configure Celery and Redis for the deployed environment.
- Confirm the business timezone and reminder schedule.
- [x] Add notification history, deduplication, failure recording, and safe retry.
- [x] Add tracked service, odometer, special-maintenance, retirement, transfer, and follow-up event paths.
- Test registration, service, calibration, odometer, special-maintenance, retirement, and transfer emails through the approved real provider and mailbox matrix.

### 7. Prepare production deployment

- [x] Add environment-driven production values and verify `check --deploy` with a production-shaped configuration.
- Provision and accept the real static/private-media hosting, backups, HTTPS, MySQL, Redis, worker, Beat, monitoring, and logging services using `docs/PRODUCTION_DEPLOYMENT.md`.
- Add error monitoring, health checks, logging, backup, and restoration procedures.
- Add pagination and performance testing for large fleets.
- Complete a user-acceptance checklist for each role.

### 8. Optional fuel and tire modules

Only after essential work is stable:

- Add supported forms, pages, permissions, and imports.
- Repair tire distance calculations.
- Add dedicated tests and analytics validation.

### 9. Modernize the visual design and user experience

Only after security, essential workflows, and production reliability are complete:

- [x] Create a consistent, modern visual system for navigation, dashboards, tables, forms, filters, status messages, and reports.
- [x] Improve the shared mobile and tablet responsiveness; continue checking supplier-specific and uncommon legacy screens as they are used.
- [x] Correct narrow-screen analytics heading and export-control overflow found during GUI verification.
- [x] Make common actions easier to find on dashboards and essential workflow list pages; continue simplifying uncommon legacy workflows.
- [x] Add clearer empty states, validation feedback, confirmations, and success messages to the shared experience; loading states remain future work for long-running operations.
- [x] Improve baseline accessibility with labels, keyboard focus states, contrast, and readable sizing; representative-user validation remains required before deployment.
- [x] Replace inconsistent authentication and 2FA pages with a unified company-branded experience.
- Validate the redesigned interface with Admin, Manager, and User representatives before deployment.

## Applied Database Migrations

Migration `tracking/migrations/0007_transfer_item_id_as_text.py` changes transfer item identifiers from numbers to text so both numeric car IDs and tool internal numbers can be recorded. It was applied on 11 August 2026 after creating and hash-verifying a timestamped SQLite backup in the ignored `backups/` directory.

The built-in MFA migrations create the authenticator records used for TOTP and recovery codes. They were applied on 11 August 2026 after a second hash-verified backup.

The dependency upgrade added `admin_interface` migrations `0031` and `0032` plus MFA migration `0003_authenticator_type_uniq`. They were first tested against a disposable database, then applied on 11 August 2026 after creating and SHA-256-verifying `backups/db-before-dependency-upgrade-20260811-055248.sqlite3`.

Migration `tracking/migrations/0008_accident_excess_nonnegative.py` prevents negative recorded company accident costs at the database level. It was covered by the full 52-test suite and a disposable GUI migration, then applied on 11 August 2026 after creating and SHA-256-verifying `backups/db-before-accident-constraint-20260811-072335.sqlite3` (`EFC952EACB1D63B543EE4DC8BEF37E7F69C51A4B0B183DC28F73E6028F84B8C2`).

Migrations `0009`-`0011` add vehicle lifecycle/history, retirement tasks, custody batches, immutable per-asset ledger entries, reversals, warehouses, and transfer follow-up audit fields. Each migration was tested and applied on 12 August 2026 after a hash-verified database backup.

Migration `tracking/migrations/0012_company_locations.py` generalizes warehouses into Company Locations while preserving all existing custody foreign keys. Existing rows default safely to Warehouse; the migration adds Office/Warehouse type, address, responsible manager, notes, activity timestamps, and the supporting list/profile/manage workflow. It was covered by the full 75-test suite and applied on 12 August 2026 after SHA-256 verification of `backups/db-before-company-locations-20260812-102415.sqlite3`.

Migration `tracking/migrations/0013_email_alerts.py` adds configurable shared alert mailboxes and auditable notification delivery history. It includes Fleet Manager, State Manager, and Admin Alert responsibilities; category routing; one primary State Manager per state; optional user linking; change auditing; deduplication; failure recording; and safe Admin retry. It was covered by the full 82-test suite and applied on 12 August 2026 after SHA-256 verification of `backups/db-before-email-alerts-20260812-103754.sqlite3` (`2F3A88A932EF8A1A447A87B981A6395110818B64FA9EACA92F99BCB6F67FD0CF`).

Migration `tracking/migrations/0014_controlled_devices.py` adds controlled-device classification, condition, calibration-required status, and optional employee custody to Tool. All existing tools default safely to ordinary, Good-condition tools; no existing asset is automatically treated as controlled. It was covered by the full 88-test suite and applied on 12 August 2026 after SHA-256 verification of `backups/db-before-controlled-devices-20260812-104651.sqlite3` (`DC484B604D0332059D20DEEDB0D29765E467C0436629E045F0C16D8699E46D5F`).

Migration `tracking/migrations/0015_searchable_tool_catalogue.py` creates the reviewed Tool Catalogue and removes the fixed code-only dropdown restriction. It seeds every previously approved type plus all names already present in company data, applies case-insensitive duplicate protection, records handling suggestions and audit fields, and preserves Tool records as text references so catalogue deactivation never destroys or renames history. All 65 existing tools and all 41 distinct live names were accounted for; the resulting catalogue contains 146 entries with none missing. It was covered by the full 94-test suite and applied on 12 August 2026 after SHA-256 verification of `backups/db-before-searchable-tool-catalogue-20260812-105902.sqlite3` (`264A759ECCD754B277239881BE6090396E0496362860045E9F1F6A3BE3BB7B1B`).

Migrations `tracking/migrations/0016_vehicle_monitoring_special_maintenance.py` and `0017_odometer_tracking_start.py` add auditable QR odometer submissions, suspicious-reading evidence/review, protected compressed fuel receipts, submitter/reviewer history, a stable seven-day first-reading baseline, and fleet-managed special maintenance with recurrence and completion evidence. They were covered by the full 121-test suite and applied on 22 August 2026 after integrity-checked backups. The final post-migration backup is `backups/asset-tracker-20260822-120910Z.sqlite3` with SHA-256 `6CF7F725BA4A5A3840817C762BC2689FC252260CAE5437839ABD73A409E22569`.

Database migrations must continue to follow this process:

1. Create and verify a database backup.
2. Test the migration against a disposable copy.
3. Confirm existing car transfer records remain readable.
4. Then run:

```bash
python manage.py migrate
```

## Account Security

After signing in, open **Security** and activate an authenticator app. Scan the QR code, enter the current six-digit code, then download and store the recovery codes somewhere separate from the device.

Admin and Manager accounts cannot use operational pages until enrollment is complete. Standard users may opt in. See `docs/AUTHENTICATION.md` for recovery procedures and the future Microsoft Entra plan.

## Local Setup

Create and activate a virtual environment, then install dependencies:

```bash
python -m venv .venv
python -m pip install -r requirements.txt
python manage.py migrate
```

On Windows, run the application and management commands through `.venv\Scripts\python.exe`. Do not use the machine-wide Python installation for this project; it may contain older Django/allauth versions and does not represent the supported runtime.

Copy `.env.example` to `.env` and replace example values. The current code reads environment variables but does not automatically load `.env`; load it through the shell or deployment service.

Run checks and tests:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test tracking
```

Never run import experiments or tests against the operational database.

## Contribution Rules

- Agree on a plan before changing behavior or data structures.
- Preserve unrelated work in the existing dirty worktree.
- Add a regression test with each defect repair where practical.
- Keep security, access control, and data integrity ahead of new features.
- Treat analytics, PDF imports, and accident tracking as essential.
- Treat fuel and tire management as optional.
- Do not commit real credentials, databases, invoices, or personal information.
- Back up data before migrations or cleanup operations.
- Update this README when a status changes.
