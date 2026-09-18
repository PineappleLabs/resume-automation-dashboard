# Gmail ingestion worker

Reads the user's Gmail inbox, classifies messages as job leads via Claude, extracts
mentioned interview dates, and upserts both into the same tables
[`services/api`](../api/README.md) reads. First full Gmail slice from
[`docs/planning/job-search-platform-plan.md`](../../docs/planning/job-search-platform-plan.md)'s
Phase 1 — auto status-transition-from-replies, `.ics` attachment parsing, and Gmail send are
later passes.

## Setup

1. **Google Cloud OAuth client** (one-time, per Google account): create a project, enable
   the Gmail API, configure the OAuth consent screen (Testing mode — add your own email as
   a **Test user**, or refresh tokens can expire after 7 days regardless of activity), and
   create an OAuth client of type **Desktop app**. Download the JSON and save it as
   `services/ingest_gmail/secrets/client_secret.json` (gitignored).

2. Venv + install (needs `packages/jobsearch_db` for the shared models, and
   `packages/resume_pipeline` for its `slugify()` helper, used to assign each ingested
   lead a `resume_job_slug` so the Tailor button works on it):

   ```powershell
   py -3.12 -m venv services\ingest_gmail\.venv
   services\ingest_gmail\.venv\Scripts\Activate.ps1
   pip install -e packages\jobsearch_db
   pip install -e packages\resume_pipeline
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
  pattern as `resume_pipeline.select.select_for_job`. A `Lead` (`source='gmail'`,
  `source_ref=<gmail_thread_id>`) plus an initial `status_history` row
  (`changed_by='system'`) is only created when `is_job_lead=true`, confidence clears
  `CLASSIFICATION_CONFIDENCE_THRESHOLD` (default `0.75`), **and** the extracted location
  satisfies `TARGET_LOCATION_DESCRIPTION` (default `"Atlanta, Georgia, or fully remote"` —
  edit in `.env` to change). Every classified message still gets its `location` and
  `location_ok` stored on `email_messages` regardless, so a rejected-by-location lead is
  visible in the data even though no `Lead` row was made for it.
- **`resume_job_slug`**: assigned via `ingest_gmail/slugs.py` (mirrors
  `services/api/app/slugs.py`) the moment a `Lead` is created — required for the dashboard's
  Tailor button, which calls `resume_pipeline.service.tailor_lead()` with it.
- **`received_at`**: set to the thread's *earliest* known message time
  (`MIN(email_messages.received_at)` across the thread), not whichever message happened to
  trigger lead creation — a full resync doesn't guarantee messages arrive in chronological
  order, so the message that first classifies as a qualifying lead isn't necessarily the
  thread's first message.
- **Interview date detection**: `classify_email()` also extracts, per message,
  `interview_mentioned`/`interview_datetime`/`interview_type`/`interview_location_or_link`/
  `interview_confidence` in the same Claude call (no added cost). When a message states a
  specific interview/call date and `interview_confidence` clears
  `INTERVIEW_CONFIDENCE_THRESHOLD` (default `0.75`), an `InterviewEvent` is created
  (`source='gmail_parsed'`) on the thread's lead — attached even if *that specific message*
  isn't independently judged a fresh job lead (e.g. a one-line "Confirmed for Thursday!"
  reply on an already-existing lead's thread still gets its date parsed and attached).
  Re-mentioning the same date/time on the same lead is deduplicated (no double-booking from
  an invite + a "confirmed!" reply). This only looks at the single message being analyzed,
  not the full thread history — a reply that just says "sounds good" with the date implied
  by context rather than restated won't be caught; extend to multi-message thread context
  later if that turns out to matter in practice. `.ics` calendar-attachment parsing (as
  opposed to a date written in the message body/subject) isn't implemented.

## Testing

```powershell
pytest services\ingest_gmail
```

Runs against `jobsearch_test` with a hand-rolled fake Gmail `service` and a monkeypatched
`classify_email` — no real network calls, no real Claude calls, no OAuth needed. Covers
idempotent re-runs, the prefilter gate, the confidence threshold gate, the location-filter
gate, the 404 stale-cursor fallback, `received_at` reflecting the thread's earliest message
regardless of processing order, and interview-event creation/dedup/confidence-gating
(including attaching to an already-existing lead from a reply that isn't independently a
fresh lead). The interactive `authorize` flow and a real end-to-end run against an actual
mailbox aren't covered by these tests — they need a human at the keyboard.

## Not built yet

Reply-monitoring / auto status updates (interview *dates* are auto-detected — see above —
but a reply doesn't change `Lead.status`), `.ics` calendar-attachment parsing, Gmail send,
LinkedIn ingestion, the auto-apply agent, Docker/infra, unattended scheduling. Full checklist:
[`docs/planning/TODO.md`](../../docs/planning/TODO.md).
