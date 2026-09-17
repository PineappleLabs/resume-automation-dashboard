# Job Search Platform (monorepo)

This repo started as a standalone resume-tailoring CLI and is growing into a job-search
automation platform: Gmail/LinkedIn lead ingestion, a tracking dashboard, and an AI-assisted
application agent, all built on top of the same tailoring pipeline.

## Layout

- [`packages/resume_pipeline/`](packages/resume_pipeline/README.md) — the resume tailoring
  pipeline (select → fit → render). Fully standalone: no dependency on anything below.
- `services/` — dashboard API, Gmail/LinkedIn ingestion workers, and the auto-apply agent
  (not built yet).
- `infra/` — Docker Compose files and reverse-proxy config for the homelab deployment
  (not built yet).

See `packages/resume_pipeline/README.md` for the resume CLI, which works exactly as it always
has and will keep working standalone throughout the rest of this build-out.
