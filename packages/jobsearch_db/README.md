# jobsearch-db

Shared SQLAlchemy models and the single Alembic migration history for the job-search
platform's Postgres database. `services/api` and `services/ingest_gmail` both depend on
this as an editable install — neither owns its own copy of the schema or its own migrations.

## Setup

```powershell
Copy-Item packages\jobsearch_db\.env.example packages\jobsearch_db\.env
# edit packages\jobsearch_db\.env and set DATABASE_URL
```

`DATABASE_URL` lives here canonically — `services/api` and `services/ingest_gmail` don't
set it in their own `.env` files, matching how `packages/resume_pipeline/.env` is the one
canonical home for `ANTHROPIC_API_KEY`.

## Migrating

Run from anywhere in the repo, pointing `-c` at this package's `alembic.ini`:

```powershell
alembic -c packages\jobsearch_db\alembic.ini upgrade head
```

New migration after changing `jobsearch_db/models.py`:

```powershell
alembic -c packages\jobsearch_db\alembic.ini revision --autogenerate -m "description"
```

Always hand-check the generated diff — autogenerate can miss `CheckConstraint`s.

## Testing

```powershell
pytest packages\jobsearch_db
```

Runs against a separate `jobsearch_test` database (drop/recreate all tables per test).
