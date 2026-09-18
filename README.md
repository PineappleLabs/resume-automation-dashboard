# Job Search Platform (monorepo)

This repo started as a standalone resume-tailoring CLI and is growing into a job-search
automation platform: Gmail/LinkedIn lead ingestion, a tracking dashboard, and an AI-assisted
application agent, all built on top of the same tailoring pipeline.

## Layout

- [`packages/resume_pipeline/`](packages/resume_pipeline/README.md) — the resume tailoring
  pipeline (select → fit → render). Fully standalone: no dependency on anything below.
- [`packages/jobsearch_db/`](packages/jobsearch_db/README.md) — shared SQLAlchemy models and
  the one Alembic migration history for the leads database, used by both services below.
- [`services/api/`](services/api/README.md) — FastAPI + HTMX leads dashboard, with manual
  lead entry and a Tailor button wired to the pipeline above.
- [`services/ingest_gmail/`](services/ingest_gmail/README.md) — Gmail inbox ingestion:
  OAuth, incremental sync, LLM classification, upserts into the same leads table the
  dashboard reads. LinkedIn ingestion and the auto-apply agent are not built yet.
- `infra/` — Docker Compose files and reverse-proxy config for the homelab deployment
  (not built yet — everything above runs natively on Windows for now).

See `packages/resume_pipeline/README.md` for the resume CLI, which works exactly as it always
has and will keep working standalone throughout the rest of this build-out.
