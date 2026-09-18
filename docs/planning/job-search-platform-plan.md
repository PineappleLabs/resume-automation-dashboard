# Job-Search Automation Platform — Implementation Plan

> Status: **Phase 0 complete** (see [Phased rollout](#phased-rollout) below). This is the
> plan drafted before Phase 0's restructuring; file paths in the "Critical files" section
> refer to the pre-restructure layout (`src/...`) and now live under
> `packages/resume_pipeline/resume_pipeline/...`.

## Context

The user has a working local CLI (`C:\Users\welte\Documents\resume`, Python, not yet a git repo) that tailors a one-page LaTeX resume to a job description: `content/content.yaml` holds structured, ID-tagged resume content; `src/select.py` calls the Anthropic API with a forced tool-call to pick which content IDs fit a given job description; `src/fit.py` trims to one page; `src/render.py` compiles the result to PDF via Tectonic. It works well as a single-user, single-job tool but everything is manual and file-based (job descriptions dropped in as `.txt`, outputs as flat files in `jobs/<slug>/`).

The user wants to turn job-search *sourcing* and *tracking* into an automated pipeline built on top of this existing tailoring logic: watch Gmail and LinkedIn for recruiter messages/job leads, track every lead's status through to offer/rejection (including auto-updating status from Gmail replies), present it all on a dashboard, and — when the user targets a specific posting — have an AI agent drive the actual online application, stopping short of the final submit for human confirmation. This is a genuinely large system (multiple ingestion pipelines, a datastore, a web app, and a browser-automation agent), so it's being planned as a phased build rather than one shot, hosted on the user's homelab (`bigpineapple`, reachable via SSH) rather than staying local.

Key decisions already made with the user, driving the design below:
- **LinkedIn**: real browser automation (Playwright, logged in as the user), polling a few times/day — not a paid scraper API, not deferred.
- **Auto-apply**: a Claude-driven browser agent (Playwright + a bespoke Claude tool-use loop), reusing the user's existing Claude access — not Gemini-in-Chrome — and it must stop before any submit action for human confirmation.
- **Existing CLI stays fully usable, standalone, throughout the rollout.** The user wants to keep using `python -m resume_pipeline.cli tailor ...` by hand while the dashboard/services are being built and tested — the pipeline package must never gain a hard dependency on Postgres/the API/any running service, so the original commands keep working identically with zero setup beyond what they need today.
- **Calendar/scheduling on the dashboard**: each lead can have upcoming interview/call events, and the main lead list is sortable by soonest upcoming event.
- **Reply drafting**: tailoring a resume for a recruiter/LinkedIn-sourced lead should also produce a ready-to-send reply (email or LinkedIn message body) with the tailored resume attached, not just the PDF alone.
- **Homelab shape** (confirmed via SSH recon of bigpineapple): Docker Compose host (~50 containers), reverse proxy is **SWAG** (nginx + Let's Encrypt) on domain `acomos.us`, convention is one stack per app under `/home/bp/infra/stacks/<name>/docker-compose.yml` joining an external `swag-network` with no published host ports, plus a matching proxy-conf. **No SSO exists today** — all auth blocks in SWAG's template are commented out. An OpenVPN server container already runs on the box. **Watchtower** auto-updates images and must be excluded for this stack's containers (would silently drift Tectonic/Playwright/Chromium versions).
- **Exposure**: dashboard will be **VPN-only** (reachable only over the existing OpenVPN server), not a public SWAG subdomain — given it will hold recruiter emails, a LinkedIn session, and can submit real applications.
- **Repo structure**: turn the existing folder into a single monorepo (`git init` it) containing the existing pipeline as a package plus the new services, rather than a separate repo.
- **Dev/test sequencing**: build and verify everything **locally first** (this Windows PC — no Docker, no SSH to the homelab) through the phases below; only once a phase works locally does it get containerized and pushed to `bigpineapple`. Phase 0 was originally verified via Docker on the homelab; it has since been re-verified running natively on Windows (Python 3.12 venv + a native Tectonic 0.17.0 Windows build) so local iteration doesn't require Docker at all until a phase is ready to deploy.

## Architecture

Single monorepo, Python-first (matches the existing pipeline), Postgres-backed, no message broker — a solo homelab project doesn't need Redis/Celery; APScheduler polling loops plus a Postgres-backed run table cover every async need here.

```
resume/                                  (git init here; becomes the monorepo root)
├── pyproject.toml
├── packages/
│   └── resume_pipeline/                 (today's src/, packaged with minimal changes)
│       ├── resume_pipeline/
│       │   ├── cli.py                   (existing click CLI — unchanged behavior)
│       │   ├── schema.py  select.py  fit.py  render.py  import_linkedin.py
│       │   └── service.py               (NEW: tailor_lead() facade the API/agent call)
│       ├── content/content.yaml
│       ├── templates/
│       └── tests/                       (NEW pytest suite — none exist today)
├── services/
│   ├── api/                             (FastAPI backend + dashboard)
│   │   ├── app/main.py
│   │   ├── app/models.py                (SQLAlchemy: Lead, StatusHistory, EmailThread,
│   │   │                                  EmailMessage, LinkedInMessage, Application, AgentRun)
│   │   ├── app/routers/{leads,applications,agent_runs}.py
│   │   ├── app/classify.py              (shared LLM classifier used by both ingestion workers)
│   │   ├── app/templates/                (Jinja2 + HTMX dashboard)
│   │   ├── alembic/
│   │   └── Dockerfile
│   ├── ingest_gmail/       (worker.py, gmail_client.py, Dockerfile)
│   ├── ingest_linkedin/    (worker.py, linkedin_session.py, Dockerfile)
│   └── autoapply_agent/    (worker.py, browser_agent.py, tools.py, Dockerfile)
├── infra/
│   ├── docker-compose.yml               (local/dev)
│   ├── docker-compose.prod.yml          (bigpineapple overrides: swag-network external, no host ports, watchtower-exclude label)
│   ├── swag/jobsearch.subdomain.conf    (kept for reference/VPN-internal routing; no public DNS)
│   └── .env.example per service (no single global .env)
└── jobs/  →  shared Docker volume mounted at /data/jobs in every service
```

**Data flow**: Gmail/LinkedIn workers poll → shared LLM classifier tags job-lead vs. not → upsert into Postgres `leads` → dashboard lists leads → user clicks **Tailor** → API calls `resume_pipeline.service.tailor_lead()` (same `select_for_job` → `fit_to_one_page` → `render_and_compile` pipeline, untouched) → PDF lands in `/data/jobs/<slug>/` → user clicks **Apply Now** with a target URL → `autoapply_agent` re-tailors if needed, drives Playwright + Claude tool-use to fill the form, **stops before submit**, writes a field/screenshot snapshot → dashboard shows an Application Preview → user clicks **Confirm & Submit** → agent performs only that final click.

### Why these technology choices
- **FastAPI + SQLAlchemy + Alembic**: same language as the pipeline, no interop layer.
- **PostgreSQL** over SQLite: multiple concurrent writers (two ingestion workers, the API, the auto-apply agent) — SQLite's single-writer lock is a real risk; Postgres is one more Compose container and the homelab already runs similar databases.
- **APScheduler in-process + a Postgres `agent_runs` table as a queue**: no Redis/Celery/RabbitMQ. Justified purely by scale — one user, low message volume — and it avoids extra infra to operate solo.
- **Server-rendered Jinja2 + HTMX (+ light Alpine.js)** for the dashboard, not a separate React/Vite app: this is an internal single-user CRUD/status tool, the repo already uses Jinja2 for the resume template, and it avoids a second build toolchain. A richer SPA is the natural upgrade path later if needed, not now.
- **Playwright + a bespoke Claude tool-use loop** (not generic desktop computer-use) for both LinkedIn scraping and auto-apply: form-filling is DOM-addressable and structured; a tool-use loop over the page's accessibility tree is more precise and far easier to run unattended headless in a container than full computer-use.

## Data model (sketch)

- `leads(id, company, role_title, source[gmail|linkedin|manual], source_ref, jd_text, jd_url, recruiter_name, recruiter_contact, received_at, status[new|tailoring|tailored|applied|interviewing|rejected|offer|withdrawn|archived], resume_job_slug, created_at, updated_at)`
- `status_history(id, lead_id, old_status, new_status, changed_by[system|user|agent], confidence, reason, changed_at)` — append-only audit trail.
- `email_threads(id, lead_id nullable, gmail_thread_id, gmail_history_id, last_message_id, last_synced_at)` — the `history_id` cursor enables incremental Gmail sync.
- `email_messages(id, thread_id, gmail_message_id UNIQUE, from_addr, subject, body_text, received_at, direction, classification, classification_confidence)`
- `linkedin_messages(id, lead_id nullable, conversation_id, sender_name, message_text, received_at, scraped_at)`
- `applications(id, lead_id, target_url, status[draft|awaiting_confirmation|submitted|failed], resume_pdf_path, form_field_snapshot JSONB, agent_run_id, submitted_at)`
- `agent_runs(id, kind[auto_apply|gmail_poll|linkedin_poll], lead_id nullable, status, started_at, finished_at, log_ref)`
- `interview_events(id, lead_id, scheduled_at, type[phone_screen|technical|onsite|call|other], location_or_link, notes, source[manual|gmail_parsed], created_at, updated_at)` — a lead can have several (screen → onsite → offer call); the dashboard's main lead list sorts by `MIN(scheduled_at)` across each lead's future events, soonest first, with leads that have none sorting last.
- `reply_drafts(id, lead_id, channel[email|linkedin], subject, body_text, resume_pdf_path, status[draft|sent|dismissed], created_at, sent_at)` — one per tailoring run against a recruiter/LinkedIn-sourced lead.

PDFs/artifacts stay on disk under `/data/jobs/<slug>/...` (matching today's pipeline); the DB stores metadata and pointers only.

## Gmail ingestion

- **Gmail API**, not IMAP — `users.history.list` gives the incremental-sync cursor (`email_threads.gmail_history_id`) needed to catch replies on existing threads without re-scanning the mailbox. Gmail expires history after ~7 days idle, so the worker needs a fallback full-resync (`users.messages.list?q=newer_than:Nd`) when a stored cursor goes stale.
- **OAuth**: Desktop/Installed-App client, one-time interactive consent, refresh token stored on-box with restricted permissions. Kept in Google's "Testing" publishing status to skip app verification — flagged as a risk below since `gmail.readonly` is a sensitive scope and unverified-app refresh-token lifetime policy should be re-checked at implementation time.
- **Classification**: cheap rule prefilter (known ATS/recruiter domains, subject keywords) to cut volume, then an LLM forced-tool-call classifier (`classify_email` tool) — same pattern already proven in `src/select.py` — returning `{is_job_lead, company, role_title, confidence}`.
- **Reply/status monitoring**: inbound messages on a thread already linked to a lead get classified for status-change signal (rejection/interview/offer language). High-confidence transitions auto-append to `status_history`; low-confidence ones surface in the dashboard for manual confirmation instead of silently changing status.

## LinkedIn ingestion

- Playwright `launch_persistent_context` against a volume-mounted profile dir, logged in **once** interactively to survive 2FA/checkpoints (e.g. a brief noVNC session over the VPN, or copying a `storage_state.json` produced locally via SCP).
- Headless polling a few times/day via APScheduler; `xvfb` as a fallback if headless detection triggers a challenge; randomized timing/jitter.
- Extraction: walk Messaging, pull sender/text/timestamp/profile-URL per conversation, store to `linkedin_messages`, run through the same shared classifier module as Gmail, upsert into `leads`.
- Ban-risk mitigation: one real account doing both manual and automated activity — throttle aggressively, ship a kill-switch env var to instantly disable ingestion if LinkedIn issues any warning, and keep a manual "quick-add lead" path in the dashboard as a fallback if ingestion ever gets throttled or banned.

## Auto-apply agent

1. User clicks **Apply Now** with a lead + target URL → API inserts `applications(status=draft)` + `agent_runs(status=queued)`.
2. Worker picks up the run and **first re-invokes the unchanged existing pipeline** (`resume_pipeline.service.tailor_lead()`) to produce/refresh the tailored PDF for this specific posting.
3. Agent launches Playwright, navigates to the URL, runs a Claude tool-use loop to fill fields (contact info, resume upload, screening questions) using lead + resume data as context.
4. **Hard stop before submit** — the agent's tool set has no "submit" tool at all. It writes every filled field + a screenshot to `applications.form_field_snapshot` and sets `agent_runs.status=awaiting_confirmation`.
5. Dashboard renders an Application Preview (tailored PDF + filled-field table) with one **Confirm & Submit** action — the only code path that can trigger the final click, via a separate API call that re-attaches to the held-open browser session.
6. On bot-detection/CAPTCHA/timeout: fail gracefully to "needs manual completion," never blind-retry.

## Reply drafting & interview scheduling

**Reply drafts.** `resume_pipeline.service.tailor_lead()` gains a second output for `source in {gmail, linkedin}` leads: alongside the tailored PDF, it makes one more Anthropic call (same forced-tool-call style as `select_for_job`, e.g. a `draft_reply` tool) that takes the recruiter's message text + the tailored `Selection` and returns a `{subject, body_text}` reply — channel-appropriate (an email with a greeting/sign-off and PDF-attachment framing for Gmail leads, a shorter message body for LinkedIn leads). This is stored as a `reply_drafts` row and shown on the lead's dashboard page next to the resume PDF, editable before use. **Sending is a separate, explicit, human-confirmed action** — same posture as auto-apply's submit gate: for `channel=email` the dashboard can offer a "Send via Gmail" button that calls `users.messages.send` with the tailored PDF attached and the thread's `In-Reply-To`/`References` headers set so it lands correctly in the existing thread, but only on click, never automatically; for `channel=linkedin` the draft is copy-to-clipboard only in an early phase (sending a LinkedIn message via Playwright is a further automation step, deliberately deferred past Phase 3's read-only scraping to keep ban risk contained). `reply_drafts.status` moves `draft → sent` only once the user-confirmed send actually completes.

**Interview/call scheduling.** `interview_events` rows are created two ways: (1) manually from the dashboard when the user schedules something themselves, and (2) opportunistically parsed out of classified Gmail replies — the same reply-classification step used for status updates (`Phase 2`) also checks for scheduling language/calendar-invite attachments (`.ics` parsing) and proposes an event with `source=gmail_parsed`, surfaced for one-click confirm rather than silently added (same confidence-gated pattern as status transitions, to avoid a misread email creating a phantom interview). The main dashboard lead list has a "Next event" column and a default sort by soonest upcoming `interview_events.scheduled_at`, so the leads needing the most immediate attention surface first.

## Secrets & security

- Per-service `.env` files under `/home/bp/infra/stacks/jobsearch/<service>/.env` (matches the homelab's existing convention), `chmod 600`, owned by `bp`, gitignored from the very first commit — this repo has never had version control, so enforce this from day one rather than retrofitting later.
- Docker Compose file-based `secrets:` is sufficient for a single host; no Vault/Infisical needed unless the user later wants centralized rotation.
- Gmail refresh token and LinkedIn `storage_state.json` are password-equivalent: same restricted-file treatment, never logged.
- **VPN-only exposure** (per decision above): no public SWAG route/DNS for this stack; reachable only over the existing OpenVPN server. Still add the dashboard's own login (even on a private network, defense in depth given the sensitivity of the data).
- Add a Watchtower opt-out label to every new container so a surprise base-image update doesn't silently change the Tectonic/Playwright/Chromium version underneath the pipeline.

## Phased rollout

- **Phase 0 — Repo hygiene + library wrap. ✅ Done.** `git init` this folder as the monorepo root; move existing code under `packages/resume_pipeline/` with only import-path changes; add `service.py` facade + a pytest suite (stub the Anthropic client; pure tests for `fit.py`/`render.py`); Dockerize with a pinned Tectonic install; confirm `python -m resume_pipeline.cli tailor/render/inventory/verify-ats` behave identically both on the host and in-container, with **no dependency on Postgres or any new service** — this standalone path must keep working through every later phase since the user will keep using it directly while the dashboard is being built out.
  - Verified: 7-test pytest suite passing; Dockerfile built and run on `bigpineapple` over SSH with Tectonic 0.17.0 (required adding `libgraphite2-3` — the prebuilt binary needs it and fails silently otherwise); container output confirmed byte-identical to host output (only CRLF/LF difference).
  - Re-verified locally on Windows (2026-09-17): Python 3.12 venv, `pip install -e ".[dev]"`, native `tectonic-0.17.0-x86_64-pc-windows-msvc` installed to `%LOCALAPPDATA%\tectonic\`; 7-test pytest suite passes; `python -m resume_pipeline.cli master` and `verify-ats` run end-to-end with no Docker involved. This is now the primary dev loop for every later phase — Docker/homelab stays the deployment target, not the dev target.
  - Repo pushed to [github.com/PineappleLabs/resume-automation-dashboard](https://github.com/PineappleLabs/resume-automation-dashboard).
- **Phase 1 — Gmail ingestion + dashboard. 🟢 Done and verified against the real mailbox.**
  Postgres + `api` service + dashboard (own login); manual **Tailor** button wired to the
  Phase 0 facade; `interview_events` support: manual add + the "next event" sort column;
  `ingest_gmail` worker with OAuth + incremental sync + a shared LLM classifier upserting
  leads (`source='gmail'`), gated on a location filter (Atlanta, GA or fully remote, per the
  user's requirement). Schema/migrations extracted into `packages/jobsearch_db`, shared by
  both services rather than owned by `services/api` alone, once `ingest_gmail` became a
  second consumer of the same tables. Reply-draft output for Gmail-sourced leads is still
  deferred to Phase 2.
  - **First pass** (2026-09-17, no Docker): native PostgreSQL 17; `services/api`
    (FastAPI + SQLAlchemy 2.0 + Alembic + Jinja2/HTMX, htmx/Alpine vendored locally) with
    manual quick-add leads, status history, interview events; full loop driven through the
    actual browser (login, quick-add, HTMX status/event updates, soonest-event sort
    confirmed with 3 leads, logout); 6/6 pytest passing.
  - **Tailor success path verified** (2026-09-17): once the user added a real
    `ANTHROPIC_API_KEY` to `packages/resume_pipeline/.env`, clicked Tailor on a real lead
    through the dashboard — real Claude call, one-page PDF generated into
    `packages/resume_pipeline/jobs/<slug>/`, download link confirmed working.
  - **`packages/jobsearch_db` extraction** (2026-09-17): `services/api/app/db.py`/
    `models.py` moved to a shared package and reduced to two-line re-export shims (zero
    changes needed in routers/`slugs.py`/tests, since all of them already used relative
    imports); `DATABASE_URL` moved to `packages/jobsearch_db/.env`, its new canonical home
    (same sharing pattern as `ANTHROPIC_API_KEY`); services/api's existing 6 tests still
    pass unmodified; 6 new `jobsearch_db` model tests added (constraint/cascade checks,
    including confirming `email_threads.lead_id` does `SET NULL` not `CASCADE` on lead
    delete).
  - **Gmail worker built** (2026-09-17): `email_threads`/`email_messages` tables added via
    a second migration (`gmail_history_id` as `BigInteger`, not `String` — avoids a
    lexicographic-`MAX()` bug on the sync cursor); OAuth module (interactive `authorize`,
    silent-refresh `load_credentials`); rule prefilter before the Claude classifier;
    `run_once()` sync orchestration with incremental (`history.list`) + full-resync
    (`messages.list`) fallback on a 404 stale cursor; CLI (`authorize`/`run-once`/`poll`).
    13/13 pytest passing against a hand-rolled fake Gmail service + `jobsearch_test`,
    covering idempotent re-runs (zero duplicate rows, zero repeat Claude calls), the
    prefilter gate, the confidence-threshold gate, and the 404 fallback.
  - **Verified end-to-end against the real mailbox** (2026-09-17): user completed
    `ingest-gmail authorize` and ran `ingest-gmail run-once` — 72 messages processed, 59
    filtered by the cheap prefilter before ever reaching Claude, 13 classified, 2 real leads
    correctly identified (high confidence) with the rest (bank/credit alerts, newsletters)
    correctly rejected. Re-run confirmed idempotent on real data: 0 new leads, 0 duplicate
    `email_messages` rows, took the incremental-sync path (not a full resync).
  - **Location filter added** (2026-09-17): user wants only Atlanta, GA or fully-remote
    roles. `classify_email()` now also extracts `location` and a `location_ok` boolean in
    the same Claude call (no added cost/latency) against a configurable
    `TARGET_LOCATION_DESCRIPTION` env var (default `"Atlanta, Georgia, or fully remote"`);
    lead creation is gated on `location_ok` in addition to `is_job_lead`/confidence.
    `email_messages` gained `location`/`location_ok` columns (migration `0003`) so a
    real-but-wrong-location lead is still visible in the data even though no `Lead` row is
    made. One already-created lead (Steneral Consulting, onsite-only in Iowa) predated this
    filter and was removed by hand at the user's confirmation; `services/ingest_gmail`'s
    suite grew to 15/15 passing with two new location-gate tests.
  - **Bug fix** (2026-09-17): the Tailor button crashed (`Path / None`) on any Gmail-sourced
    lead — `_upsert_lead()` never assigned `resume_job_slug`, unlike the dashboard's manual
    quick-add path. Fixed via `ingest_gmail/slugs.py` (mirrors
    `services/api/app/slugs.py`); regression test added.
  - **Manual refresh + interview-date parsing pulled forward from Phase 2** (2026-09-17), at
    the user's request: a **Refresh from Gmail** button on the dashboard's leads list calls
    `ingest_gmail.sync.run_once()` in-process (lazily imported in the new
    `services/api/app/routers/gmail.py`, so a missing OAuth/API key only breaks this one
    button, not app startup — the same lesson as the earlier `ANTHROPIC_API_KEY`/
    `DATABASE_URL` startup bug), redirecting back to `/leads` with a summary via query-string
    flash params. Separately, `classify_email()` now also extracts a per-message
    `interview_mentioned`/`interview_datetime`/`interview_type`/
    `interview_location_or_link`/`interview_confidence` in the same Claude call; a
    confidence-gated match creates an `InterviewEvent(source='gmail_parsed')` on the
    thread's lead (deduplicated on exact same-time re-mentions, and correctly attaches even
    when the triggering message isn't independently judged a fresh lead — e.g. a bare
    "confirmed!" reply on an existing thread). Also fixed: `Lead.received_at` for
    Gmail-sourced leads now reflects the thread's *earliest* message
    (`MIN(email_messages.received_at)`), not whichever message happened to trigger lead
    creation — full resyncs don't guarantee chronological processing order.
    `services/ingest_gmail`'s suite grew to 22/22 passing; `services/api` grew to 9/9 with a
    new `test_gmail_refresh.py`. True full-thread-context date reasoning and `.ics`
    calendar-attachment parsing are still not implemented — noted as future work.
  - See [`services/api/README.md`](../../services/api/README.md),
    [`services/ingest_gmail/README.md`](../../services/ingest_gmail/README.md), and
    [`packages/jobsearch_db/README.md`](../../packages/jobsearch_db/README.md).
- **Phase 2 — Status-update monitoring + Gmail send.** Extend `ingest_gmail` to auto-append
  `status_history` from classified replies with confidence-gated auto-update vs.
  flag-for-review (interview-date extraction itself already landed early, see above); add
  `.ics` calendar-attachment parsing to complement the body-text date extraction already in
  place; wire the dashboard's "Send via Gmail" button (`users.messages.send` with PDF
  attached, replying into the existing thread).
- **Phase 3 — LinkedIn ingestion.** `ingest_linkedin` worker with a persisted session, same shared classifier producing leads + reply drafts (copy-to-clipboard only — no automated LinkedIn sending yet), feature-flagged so it can be disabled instantly.
- **Phase 4 — Auto-apply agent.** `autoapply_agent` + `agent_runs`/`applications` tables + the dashboard's Apply Now → Preview → Confirm & Submit flow; pilot against a couple of simple ATS platforms (e.g. Greenhouse) before trusting it broadly; ship with a visible kill switch.

## Open risks to keep in view

- **LinkedIn ToS/ban exposure** is ongoing, not a one-time check — the manual quick-add fallback exists precisely for when this gets throttled.
- **Gmail OAuth verification**: unverified "Testing" apps + sensitive scopes may have refresh-token lifetime constraints under Google's current policy — re-check at implementation time; may force periodic re-auth.
- **Bot detection on target ATS platforms** (Workday, iCIMS, Greenhouse, Taleo, etc.) will vary widely — design for graceful hand-off to "finish manually," never aggressive retry.
- **Classification false positives/negatives**: always show confidence in the UI, treat classification as advisory, keep manual override easy.
- **Tectonic-in-Docker reproducibility**: resolved in Phase 0 — pinned to 0.17.0, with `libgraphite2-3` added as a runtime dependency after it was found missing.

## Verification approach per phase

- **Phase 0** ✅: ran existing `tailor`/`render`/`inventory` CLI commands inside the new Docker image (built and run on `bigpineapple`) and diffed the output against host-produced output; ran the new pytest suite.
- **Phase 1**: point `ingest_gmail` at a Gmail label seeded with a few real/sample recruiter emails, confirm leads appear correctly classified in the dashboard, confirm the Tailor button reproduces Phase-0-equivalent output.
- **Phase 2**: manually reply to a test thread with rejection/interview-style language and confirm `status_history` updates (or flags for review) as expected.
- **Phase 3**: run `ingest_linkedin` against the user's real LinkedIn inbox in a monitored/manual first run, confirm extracted leads match reality before trusting the scheduled poll.
- **Phase 4**: dry-run the auto-apply agent against a throwaway/test application form first, confirm it reliably stops at `awaiting_confirmation` with an accurate field snapshot before ever pointing it at a real job posting.

### Critical files (pre-Phase-0 paths; now under `packages/resume_pipeline/resume_pipeline/`)
- `select.py` — forced tool-call pattern to reuse for email/LinkedIn classification.
- `render.py` — Tectonic invocation, now containerized (`_find_tectonic`).
- `fit.py` — one-page trimming logic, wrapped unchanged by `service.py`.
- `cli.py` — orchestration now shared with `service.py`'s `tailor_lead()`.
- `schema.py` — Pydantic models to extend for the new SQLAlchemy schema.
