# Gmail ingestion worker

Reads the user's Gmail inbox, classifies messages as job leads via Claude, and upserts them
into the same `leads` table [`services/api`](../api/README.md) reads. First full Gmail slice
from [`docs/planning/job-search-platform-plan.md`](../../docs/planning/job-search-platform-plan.md)'s
Phase 1 — reply monitoring, `.ics` parsing, and Gmail send are later passes.

## Setup

1. **Google Cloud OAuth client** (one-time, per Google account): create a project, enable
   the Gmail API, configure the OAuth consent screen (Testing mode — add your own email as
   a **Test user**, or refresh tokens can expire after 7 days regardless of activity), and
   create an OAuth client of type **Desktop app**. Download the JSON and save it as
   `services/ingest_gmail/secrets/client_secret.json` (gitignored).

2. Venv + install (needs `packages/jobsearch_db` too, for the shared models):

   ```powershell
   py -3.12 -m venv services\ingest_gmail\.venv
   services\ingest_gmail\.venv\Scripts\Activate.ps1
   pip install -e packages\jobsearch_db
   pip install -e services\ingest_gmail
   ```

3. Copy `.env.example` to `.env`. `DATABASE_URL` and `ANTHROPIC_API_KEY` are **not** set
   here — read from `packages/jobsearch_db/.env` and `packages/resume_pipeline/.env`
   respectively, same sharing pattern used everywhere else in this repo.

4. One-time interactive authorization — opens your real browser, you sign in and grant
   `gmail.readonly` yourself (you'll see an "unverified app" warning since the client is in
   Testing status; that's expected):

   ```powershell
   ingest-gmail authorize
   ```

   Saves a refresh token to `services/ingest_gmail/secrets/token.json` (gitignored). Every
   later run refreshes it silently — you only do this once (until/unless it's revoked).

## Running

```powershell
ingest-gmail run-once   # one sync pass, prints a summary, exits
ingest-gmail poll       # runs continuously, polling every POLL_INTERVAL_MINUTES (default 30)
```

`run-once` is the one to use for manual/testing runs; `poll` isn't wired to run unattended
(no Task Scheduler/startup registration) yet.

## How it works

- **Sync cursor**: `MAX(email_threads.gmail_history_id)` across all threads. No cursor yet
  (or a `404` from Gmail on an expired one) → full resync (`messages.list?q=newer_than:7d`,
  tunable via `FULL_RESYNC_DAYS`). Otherwise incremental `history.list`.
- **Idempotency**: every fetched message gets an `email_messages` row keyed by the unique
  `gmail_message_id`, before any classification — a re-walk of already-seen messages (e.g.
  from a full resync) costs one indexed lookup each and zero repeat Claude calls.
- **Prefilter**: a small rule-based check (`ingest_gmail/prefilter.py` — known ATS/recruiter
  domains, subject/body keywords) runs before spending a Claude call. Messages that fail it
  are stored as `classification='skipped_prefilter'` and never classified.
- **Classification**: `classify_email()` (`ingest_gmail/classify.py`) — same forced-tool-call
  pattern as `resume_pipeline.select.select_for_job`. Only `is_job_lead=true` above
  `CLASSIFICATION_CONFIDENCE_THRESHOLD` (default `0.75`) creates a `Lead`
  (`source='gmail'`, `source_ref=<gmail_thread_id>`) plus an initial `status_history` row
  (`changed_by='system'`).

## Testing

```powershell
pytest services\ingest_gmail
```

Runs against `jobsearch_test` with a hand-rolled fake Gmail `service` and a monkeypatched
`classify_email` — no real network calls, no real Claude calls, no OAuth needed. Covers
idempotent re-runs, the prefilter gate, the confidence threshold gate, and the 404
stale-cursor fallback. The interactive `authorize` flow and a real end-to-end run against an
actual mailbox aren't covered by these tests — they need a human at the keyboard.

## Not built yet

Reply-monitoring / auto status updates, `.ics` scheduling parsing, Gmail send, LinkedIn
ingestion, the auto-apply agent, Docker/infra, unattended scheduling.
