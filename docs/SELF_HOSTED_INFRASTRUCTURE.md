# Self-hosted infrastructure analysis

Last reviewed: 28 August 2026.

This document answers the question: if you have two NVIDIA DGX Spark
machines connected with a fiber link and a SAS-attached storage
array, can you run the Koinonia Asset Tracker on them, and is it an
efficient use of the hardware?

The short answer is **yes, you can — but the asset tracker alone is a
rounding error on a DGX Spark, so the real decision is what else you
plan to run on the same box and whether you intend to add AI features
to the application**. Everything below is the long answer.

## TL;DR

| Question | Answer |
|---|---|
| Can the app run on it? | Yes. Django + MySQL/PostgreSQL + Gunicorn + Celery all work on Arm64 Linux. |
| Is the hardware efficient for this app alone? | **No.** A DGX Spark is roughly 100× more compute than the asset tracker needs, and the GPU is unused. |
| Is the hardware efficient for this app + LLM features? | **Yes.** OCR for invoice PDFs, fuel-receipt vision models, predictive maintenance, and natural-language search all benefit from the GB10's 128 GB unified memory. |
| Is the hardware efficient for the app + other internal services? | **Probably yes** if you already own the machines and want a single on-prem platform for several small tools. |
| What does the app actually need at minimum? | 1 vCPU, 1 GB RAM, 20 GB SSD, one static IP. A $150–$300 mini PC handles the production load for Koinonia's fleet size. |

## What the app actually requires

Profile the workload honestly before sizing hardware.

| Resource | Realistic peak | Notes |
|---|---|---|
| Concurrent users | 5–20 | One Admin, two Managers, and a handful of Users. NSW + VIC split. |
| Requests/sec | 1–10 steady, 30–50 burst | Bursts happen when someone uploads an invoice or runs an export. |
| Web process CPU | 1–2 vCPU steady | Gunicorn with 2–3 workers is plenty. |
| Database size | 100 MB–2 GB | Years of odometer readings, maintenance records, transfers, accidents, and uploaded documents. |
| Database CPU | 1–2 vCPU | MySQL or PostgreSQL with proper indexes handles this on a single core. |
| RAM | 2–4 GB | Gunicorn workers (1 GB) + database (1 GB) + cache (256 MB) + headroom. |
| Storage | 20–50 GB | Application + SQLite/DB + uploaded media + logs + a few backups. |
| Static files | < 50 MB | Bootstrap, Font Awesome, Chart.js, project images. |
| Reminder emails | 50–500/day | Daily registration, maintenance, calibration, retirement, transfer follow-up, special maintenance, weekly odometer. |
| Uploads | 5–15 MB PDF, 2–10 MB photo per file | Bounded by the existing 5 MB PDF and image compression rules. |

The honest read: a Raspberry Pi 5 (4 GB) can run the web process for this
load. SQLite can handle it. A refurbished Dell OptiPlex SFF with an
i5-12400 and 16 GB RAM is the right size for the next ten years.

## The DGX Spark + SAS reality check

A single DGX Spark provides:

- **NVIDIA GB10 Grace Blackwell superchip** with a 20-core Arm CPU (10× Cortex-X925 + 10× Cortex-A725) and a Blackwell GPU with 5th-gen Tensor Cores.
- **128 GB unified LPDDR5x memory** shared between CPU and GPU.
- **Up to 1 PFLOP of FP4 AI compute**.
- **ConnectX-7 SuperNIC** — 200 GbE or NDR200 InfiniBand depending on variant.
- **4× M.2 NVMe slots** for local storage, with a 1 TB or 4 TB NVMe included.
- **~240 W max draw**, ~150 W typical.
- **Ubuntu 24.04** out of the box.

Two of them with a fiber link and SAS storage is an HPC cluster, not
a web app host. That is not a criticism — it is a statement about
what the hardware is built for.

### What the asset tracker uses out of all that

| DGX Spark capability | What the asset tracker uses |
|---|---|
| CPU (20 cores) | ~1 core. The other 19 sit idle. |
| Unified memory (128 GB) | ~300 MB. The other 127.7 GB sits idle. |
| GPU (Blackwell) | **Nothing.** Django does not use the GPU. |
| ConnectX-7 (200 GbE) | A 1 GbE NIC would be enough. |
| NVMe (multi-GB/s) | The app issues a few hundred small writes per minute. |
| 240 W power | The asset tracker needs ~10 W. |

The two DGX Sparks together have roughly **1,500× more compute, 800×
more memory, and 200× more network bandwidth** than the application
needs. The GPU is the biggest loss: the asset tracker is pure CPU and
DB, and a GB10 was designed for FP4/BF16 tensor work, not Django.

### Total cost of ownership for the proposed setup

| Item | Approximate cost (USD) | Notes |
|---|---|---|
| 2× DGX Spark (1 TB each) | $7,998 | MSRP $3,999 each at launch. |
| 2× DGX Spark (4 TB each) | $8,998 | For larger local database. |
| 200 GbE fiber cable (direct attach, 3 m) | $200–$400 | OSFP/QSFP-DD DAC or AOC. |
| 200 GbE switch (NVIDIA SN2100, used) | $1,500–$2,500 | Required if you want more than two nodes. Direct attach is fine for two. |
| SAS HBA (per node) | $150–$400 | If the storage array uses a discrete HBA. |
| SAS-attached storage array (24-bay, 8–24 TB raw) | $2,500–$8,000 | Synology, Dell MD, HPE MSA, or similar. Hardware RAID recommended. |
| SAS cabling | $100–$300 | One cable per node, 1–3 m. |
| 1U rack shelf per node | $80–$200 | Or sit them on a desk; the Spark form factor is small. |
| UPS (1500 VA, online) | $400–$800 | Protects against brownouts for both nodes. |
| Cooling allowance | — | ~340 W continuous per node, plus storage. Plan for ~1 kW heat load per node. |
| **Total** | **$13,000–$22,000** | Excluding cooling/electrical buildout. |

For comparison, a correctly sized self-hosted stack costs:

| Item | Cost |
|---|---|
| 1× mini PC (Intel N100 / 16 GB / 512 GB NVMe) | $250–$400 |
| 1× refurbished SFF PC (i5-12400 / 32 GB / 1 TB NVMe) | $350–$500 |
| Domain + DNS | $10–$15/year |
| Cloudflare proxy (free tier is fine) | $0 |
| Let's Encrypt certificate | $0 |
| **Total** | **$350–$500** + the cost of a static IP and a small monthly bandwidth line. |

The DGX Spark setup is roughly **30–60× more expensive** than what the
asset tracker needs in steady state.

## Three architecture options

### Option 1 — DGX Sparks as the platform for the asset tracker alone

**Verdict: do not do this.** You will leave 99% of the hardware idle
and the GPU will never see a tensor. The web process will use one
core, the database will use two cores, and the other 37 cores plus
the entire GPU will sit cold. From a TCO perspective it is wasteful.
From a capability perspective it is also wasteful — a 240 W draw
versus a 10 W draw is a real difference on a 24/7 service.

### Option 2 — DGX Sparks as the platform for the asset tracker plus several other internal services

**Verdict: reasonable if you already own the machines.** Running a
dozen small internal tools (the asset tracker, a wiki, an internal
ticket system, a Grafana stack, a couple of small LLM inference
endpoints) on a pair of DGX Sparks makes sense, especially if you
want to keep all company data on-prem. The asset tracker becomes
one tenant among many, and the idle capacity is consumed by the
other services.

This is also where the storage array pays off: shared SAS storage
becomes the unified home for application data, uploaded media, model
weights, and backups. Two nodes plus shared storage plus fiber is a
real platform, not a one-app host.

### Option 3 — DGX Sparks for AI workloads, a small dedicated box for the asset tracker

**Verdict: usually the right answer.** Buy a $300–$500 mini PC or
refurbished SFF to run the asset tracker, MySQL/PostgreSQL, Redis,
Gunicorn, and Celery. Run the DGX Sparks as a separate inference
cluster. The asset tracker calls the inference cluster over the
LAN when it needs OCR, prediction, or search. This is the
"right-sized" architecture.

The fiber link between the Spark nodes stays useful for syncing
model weights, doing distributed inference, and providing a
high-availability path between inference endpoints. The asset
tracker talks to one of the Spark nodes over a normal 1 GbE
network and never touches the GPU directly.

## Recommendation

For the asset tracker alone, **Option 3** is the right answer. The
DGX Spark + SAS setup is the wrong tool for this job, in the same
way a CNC mill is the wrong tool to open a letter.

If you already own the DGX Sparks and want to use them, run the
asset tracker on them anyway and accept the inefficiency. A working
deployment on slightly over-powered hardware is much better than a
perfectly-sized deployment that never gets built. Just don't pretend
it is the efficient choice.

If you want to get **value** out of the DGX Sparks while running the
asset tracker, add AI features that use the GPU. See the next
section.

## What you actually need, regardless of hardware choice

This is the minimum viable stack for a self-hosted Django + MySQL
deployment. It works on the $300 mini PC and on the DGX Spark
without changes.

### Operating system

- Ubuntu 24.04 LTS (or 22.04 LTS) on x86_64. The asset tracker
  itself is architecture-neutral — Django and the pinned dependencies
  all work on Arm64 too, but the wider ecosystem (Docker images,
  third-party tools) is more reliable on x86_64.

### Network

- A static public IPv4 (or IPv6) address, or a Cloudflare Tunnel
  in front of the box.
- A registered domain name pointed at the address.
- Port 443 open inbound, port 80 open for HTTP→HTTPS redirect only.

### Reverse proxy

- **Caddy** is the simplest choice — automatic HTTPS via Let's
  Encrypt, simple config file, automatic cert renewal. Recommended.
- **Nginx** is the more flexible choice if you need complex routing,
  rate limiting, or buffer tuning.

### WSGI server

- **Gunicorn** with 2–4 sync workers on a 2-core box, or `--workers
  $(( 2 * $(nproc) + 1 ))` on a larger one. Pin the version in
  `requirements.txt` (already 26.0.0).

### Database

- **PostgreSQL 16** is the recommended choice for production. The
  project already supports MySQL via `DJANGO_DATABASE_ENGINE=mysql`
  and SQLite via `sqlite`. PostgreSQL is preferred for the JSON
  fields, range types, and the analytics query plan.
- **MySQL 8** is the second choice. The settings already include
  `pymysql` as the connector.
- **SQLite** is acceptable for the smallest deployments and
  PythonAnywhere. Plan to migrate when you exceed ~5 concurrent
  writers.

### Cache and message broker

- **Redis 7** for `DJANGO_CACHE_URL` and Celery broker + result
  backend. Use three logical databases (broker=0, results=1,
  cache=2).

### Background tasks

- **Celery worker** (one or more replicas) and **Celery Beat**
  (exactly one replica). Supervise both with systemd.

### Static and media

- `python manage.py collectstatic --noinput` into `DJANGO_STATIC_ROOT`.
- Serve `/static/` directly from the reverse proxy with long-lived
  cache headers.
- For media, the existing implementation already protects uploaded
  files behind authenticated download routes; do **not** expose
  `DJANGO_MEDIA_ROOT` directly via the reverse proxy.

### Email

- A real SMTP provider — Mailgun, Postmark, SendGrid, or a
  Google Workspace/Microsoft 365 mailbox with an app password. Port
  587 with TLS is the default. The 2FA admin alert mailbox, the
  reminder categories, and the delivery history all expect real
  SMTP.

### Backups

- The existing `manage.py backup_database` command works for SQLite.
  For MySQL/PostgreSQL use `mysqldump` / `pg_dump` scheduled daily.
- A second copy offsite (Backblaze B2, S3, or rsync to a second
  machine). The README already requires a restore test in a
  disposable environment before any backup is accepted.

### Monitoring

- `/health/live/` and `/health/ready/` already exist. Point an
  external uptime check (UptimeRobot, Better Stack, or a simple
  curl cron) at `/health/ready/`.
- Central log collection (Loki, Journald remote, or a simple
  `rsyslog` forward) so logs survive a box rebuild.
- Disk-space alerts on the database and media volumes.

### Process supervision

- `systemd` units for gunicorn, celery worker, celery beat, and
  the reverse proxy. Each unit should `Restart=always` and have a
  short `RestartSec`.

### Security baseline

- `DJANGO_DEBUG=false`, a real long `DJANGO_SECRET_KEY`, the
  production HTTPS origin in `DJANGO_CSRF_TRUSTED_ORIGINS` and
  `DJANGO_ALLOWED_HOSTS`, HSTS enabled after HTTPS is verified,
  `SECURE_PROXY_SSL_HEADER` set because the reverse proxy
  terminates TLS, and the existing `tracking.E001`–`E008` checks
  passing on `manage.py check --deploy`.

## AI features that would justify the DGX Spark hardware

If you keep the DGX Sparks and want to put them to work for the
asset tracker specifically, these are the features that actually
need the GPU and unified memory. Each one is a discrete project
with its own scope.

| Feature | What it does | Why it needs the GB10 |
|---|---|---|
| PDF invoice OCR | Reads scanned or photographed invoice PDFs and extracts supplier, line items, totals, dates, and vehicle identifiers. The existing `pdfplumber` + `pypdf` pipeline handles typed PDFs; a vision-language model handles scanned ones. | A 7B VLM runs comfortably in the 128 GB unified memory with room for context, batching, and multiple variants. |
| Fuel receipt OCR + audit | Reads the compressed fuel-receipt photos the system already stores, extracts station, litres, dollars, and date, and flags anomalies against historical patterns. | Same as above. The GB10 also handles image preprocessing (rotation, contrast) on the GPU. |
| Predictive maintenance | Forecasts when each vehicle is likely to need its next service, brake job, or tyre change based on odometer history, time, and historical costs. | A small time-series model or a fine-tuned LLM-with-tools runs entirely in-memory. |
| Anomaly detection on odometer readings | Flags impossible jumps, suspicious drops, or QR submissions that look automated rather than human. | Cheap on CPU; only worth the GB10 if you combine it with the other inference workloads. |
| Natural-language search over the fleet | "Which vehicle had brake work in NSW last quarter?" answered from the database without the user writing SQL. | A 7B–14B instruction-tuned LLM with function calling. The 128 GB unified memory keeps the model and the tool definitions resident. |
| Document Q&A | "What did the mechanic say about car 17's last service?" answered from the stored PDFs and notes. | Retrieval-augmented generation with a local embedding model and a small LLM. |

To wire any of these into the existing app:

- Add a new Django app (`tracking.ai` or similar) with model wrappers
  and a small HTTP API exposed to the asset tracker.
- Run the inference server (vLLM, llama.cpp server, or a custom
  FastAPI wrapper) on one DGX Spark node. The asset tracker
  forwards requests over the LAN.
- Cache embeddings in Redis; cache generations in the same Redis
  database the web app already uses.
- Add a feature flag (`DJANGO_AI_ENABLED`) so the inference
  dependency is optional and the asset tracker still works on
  PythonAnywhere or the mini PC without it.

## When the DGX Spark setup *is* the right answer

The proposed hardware is the right answer when **two or more** of
the following are true:

- You already own the DGX Sparks and want a single on-prem platform
  for several internal services, not just the asset tracker.
- You plan to add LLM features (OCR, prediction, search) that need
  the unified memory and the GPU.
- You want HA across two nodes with shared storage, and the
  alternative (two small boxes plus a shared NAS) doesn't give you
  the same failure isolation or backup story.
- You handle regulated data and want every byte to stay on
  equipment you physically control.

If only one of those is true, the asset tracker is happier on a
$300 mini PC and the DGX Sparks can do what they were built for.

## Decision matrix

| If your situation is… | Use this |
|---|---|
| "I just want the asset tracker running and I don't have spare hardware." | Mini PC or refurbished SFF + PythonAnywhere as the backup option. |
| "I have the DGX Sparks, but the asset tracker is the only thing they'll run." | Run the asset tracker on them anyway. The cost is sunk. |
| "I have the DGX Sparks and I want to add OCR, prediction, and AI search." | Run the asset tracker on the mini PC and the inference server on the DGX Sparks. Add a small `tracking.ai` app. |
| "I have the DGX Sparks and I want them to host 5+ internal services." | Run everything on them. Use the fiber link for HA, the SAS storage for shared media and backups. Treat the asset tracker as one tenant. |
| "I have nothing and I'm choosing what to buy." | Buy a $300–$500 mini PC, deploy the asset tracker there, and revisit only if user count or AI features grow. |
