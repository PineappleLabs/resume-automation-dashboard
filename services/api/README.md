# Job Search Dashboard — API

FastAPI + Jinja2/HTMX dashboard for tracking job leads, backed by Postgres. Part of
Phase 1 from [`docs/planning/job-search-platform-plan.md`](../../docs/planning/job-search-platform-plan.md):
leads, status history, and interview events — manually added or, now, ingested from Gmail by
[`services/ingest_gmail`](../ingest_gmail/README.md). Runs natively on Windows — no Docker.
Schema/migrations live in [`packages/jobsearch_db`](../../packages/jobsearch_db/README.md),
shared with the ingestion worker.

## Setup

1. Install PostgreSQL 17 (native Windows service):

   ```powershell
   winget install --id PostgreSQL.PostgreSQL.17 -e
   ```

2. Create the app role and databases (default superuser password from the winget install is
   `postgres`):

   ```powershell
   $env:PGPASSWORD = "postgres"
   psql -U postgres -h localhost -c "CREATE ROLE jobsearch_app WITH LOGIN PASSWORD 'devpassword';"
   psql -U postgres -h localhost -c "CREATE DATABASE jobsearch OWNER jobsearch_app;"
   psql -U postgres -h localhost -c "CREATE DATABASE jobsearch_test OWNER jobsearch_app;"
   ```

3. Create the venv and install this package, `jobsearch_db`, `resume_pipeline`, and
   `ingest_gmail` (all editable — the last one is needed for the dashboard's "Refresh from
   Gmail" button, which calls `ingest_gmail.sync.run_once()` in-process; see
   [`services/ingest_gmail/README.md`](../ingest_gmail/README.md) for its own OAuth setup):

   ```powershell
   py -3.12 -m venv services\api\.venv
   services\api\.venv\Scripts\Activate.ps1
   pip install -e services\api
   pip install -e packages\jobsearch_db
   pip install -e packages\resume_pipeline
   pip install -e services\ingest_gmail
   ```

4. Copy `.env.example` to `.env` and fill in `SESSION_SECRET_KEY` (e.g.
   `python -c "import secrets;print(secrets.token_hex(32))"`) and `DASHBOARD_PASSWORD`.
   `ANTHROPIC_API_KEY` and `DATABASE_URL` are **not** set here — read from
   `packages/resume_pipeline/.env` and `packages/jobsearch_db/.env` respectively (each
   shared with other services, never duplicated). See
   [`packages/jobsearch_db/README.md`](../../packages/jobsearch_db/README.md) to set up
   `DATABASE_URL` first.

5. Migrate and run:

   ```powershell
   alembic -c packages\jobsearch_db\alembic.ini upgrade head
   uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 --app-dir services\api
   ```

Visit `http://127.0.0.1:8000`, log in with `DASHBOARD_PASSWORD`.

## What's here

- Manual "quick-add" leads (company, role, JD text), plus leads ingested automatically from
  Gmail by `services/ingest_gmail` (`source='gmail'`) — LinkedIn ingestion is still later.
- **Refresh from Gmail** button on the leads list — runs a sync pass on demand (in-process,
  blocking, same as `ingest-gmail run-once`) instead of waiting for a scheduled poll; result
  summary shown via a redirect + query-string flash message (`/leads?gmail_total=...`).
- Status tracking with a full history (`status_history`), interview event scheduling
  (`interview_events` — manually added, or auto-added from a parsed Gmail date with
  `source='gmail_parsed'`, tagged "from Gmail" in the list), leads list sorted by soonest
  upcoming event.
- **Tailor** button on a lead's detail page calls `resume_pipeline.service.tailor_lead()`
  in-process (same pipeline the CLI uses, same `packages/resume_pipeline/jobs/<slug>/`
  output directory) and serves the resulting PDF.
- Single-user login: a session cookie gated by one `DASHBOARD_PASSWORD` env var. No `users`
  table, no password hashing — see `app/security.py` for why that's fine here and when it
  wouldn't be.

## Testing

```powershell
pytest services\api
```

Tests run against the `jobsearch_test` database (drop/recreate all tables per test) and
never touch `jobsearch` or `services/api/.env`.

## Not built yet

LinkedIn ingestion, reply drafts, the auto-apply agent, and Docker/homelab deployment — see
the plan doc's phased rollout.
