# Remaining work — TODO

Actionable checklist companion to
[`job-search-platform-plan.md`](job-search-platform-plan.md), which has the full
architecture/rationale and a "Current state" summary. This file is just the backlog —
update it as items land or scope changes; keep the plan doc's build log as the historical
record of *how* something was built, and this file as *what's left*.

## Phase 2 — reply drafts, status monitoring, Gmail send

- [ ] **Reply drafts.** `resume_pipeline.service.tailor_lead()` (or a sibling call) generates
      a `{subject, body_text}` reply alongside the tailored PDF for `source='gmail'` leads —
      same forced-tool-call pattern as `select_for_job`/`classify_email`. New `reply_drafts`
      table (see plan doc's Data model). Shown on the lead detail page, editable before use.
      Sending stays a separate, explicit, human-confirmed action (see next item) — a draft is
      never sent automatically.
- [ ] **"Send via Gmail" button.** Calls `users.messages.send` with the tailored PDF attached
      and `In-Reply-To`/`References` headers set so it threads correctly. Needs the
      `gmail.send` OAuth scope in addition to today's `gmail.readonly` — re-run
      `ingest-gmail authorize` after adding it (existing `token.json` won't have the new
      scope). `reply_drafts.status` moves `draft → sent` only once the send actually
      completes.
- [ ] **Auto status updates from replies.** Classify inbound messages on a thread already
      linked to a lead for status-change signal (rejection/interview/offer language).
      High-confidence transitions auto-append to `status_history` (`changed_by='system'`);
      low-confidence ones should surface for manual confirmation rather than silently
      changing status — decide the specific UI for that (a banner on the lead? a pending-review
      list on `/leads`?) before building it, since none of the current dashboard has a
      "needs confirmation" pattern yet.
- [ ] **`.ics` calendar-attachment parsing.** Today's interview-date extraction only reads
      the message body/subject text. Fetching and parsing an actual `.ics` MIME attachment
      (via `messages.attachments.get`) would catch invites where the date lives only in the
      attachment, not restated in the email body.
- [ ] **Multi-message thread context for interview dates.** Today `classify_email()` only
      sees the single message being analyzed. A reply like "Sounds good, see you then!" with
      no restated date won't be caught. Would need passing recent thread history into the
      classifier call — worth doing only if this turns out to matter in practice (check
      after a few weeks of real usage before building it).
- [ ] **Confirm-before-add for auto-parsed interview events.** Current behavior creates
      `gmail_parsed` events directly, no review step (a deliberate simplification from the
      original plan, done at the user's request). Revisit if false-positive interview events
      start showing up.

## Phase 3 — LinkedIn ingestion

- [ ] **`services/ingest_linkedin`** worker, mirroring `services/ingest_gmail`'s shape
      (`config.py`, a sync module, a CLI). New `linkedin_messages` table.
- [ ] **Playwright session**: `launch_persistent_context` against a persisted profile dir;
      one-time interactive login to survive 2FA/checkpoints. Store `storage_state.json`
      alongside `services/ingest_gmail/secrets/`-style gitignored secrets.
- [ ] **Extraction**: walk Messaging, pull sender/text/timestamp/profile-URL per
      conversation, store to `linkedin_messages`, reuse the same classifier *pattern*
      (forced-tool-call, location filter, interview-date extraction) already proven for
      Gmail — likely worth extracting the now-twice-duplicated `_resolve_schema_refs` helper
      into a small shared `anthropic_tools` helper once this second consumer exists (the
      "duplicate until a third consumer shows up" call made in `ingest_gmail/classify.py`
      resolves here).
- [ ] **Ban-risk mitigation**: throttle aggressively (start conservative — a few polls/day,
      not continuous); a kill-switch env var to instantly disable ingestion if LinkedIn
      issues any warning; the dashboard's existing manual quick-add already covers the
      fallback-if-ingestion-breaks case, so no extra fallback UI needed.
- [ ] **Manual first run**: per the plan doc's verification approach, run against the user's
      real LinkedIn inbox in a monitored/manual pass before trusting a scheduled poll.

## Phase 4 — auto-apply agent

- [ ] **`services/autoapply_agent`** worker: Playwright + a bespoke Claude tool-use loop
      (not generic computer-use) — form-filling is DOM-addressable/structured, so a
      tool-use loop over the accessibility tree is more precise and easier to run headless.
- [ ] **New tables**: `applications`, `agent_runs` (see plan doc's Data model).
- [ ] **Flow**: user clicks **Apply Now** with a lead + target URL → re-invokes
      `tailor_lead()` to refresh the PDF for this posting → agent launches Playwright, fills
      contact info/resume upload/screening questions from lead+resume context → **hard stop
      before submit** (the tool set has no "submit" tool at all) → writes filled fields +
      a screenshot to `applications.form_field_snapshot` → dashboard shows an Application
      Preview with one **Confirm & Submit** action, the only code path that can trigger the
      real submit click, via a separate call re-attaching to the held-open browser session.
- [ ] **Failure handling**: on bot-detection/CAPTCHA/timeout, fail gracefully to "needs
      manual completion" — never blind-retry.
- [ ] **Pilot conservatively**: dry-run against a throwaway/test form first; then a couple of
      simple, well-behaved ATS platforms (e.g. Greenhouse) before trusting it broadly. Ship
      with a visible kill switch from day one, not as an afterthought.

## Cross-cutting / infra

- [ ] **Docker + homelab deployment.** `infra/` is currently empty. Per the plan doc:
      Compose files (local/dev + `bigpineapple` prod overrides), SWAG proxy-conf (VPN-only,
      no public DNS), a Watchtower opt-out label on every container (a base-image bump must
      never silently drift Tectonic/Playwright/Chromium versions), per-service `.env` files
      under `/home/bp/infra/stacks/jobsearch/<service>/.env`. Not urgent while everything
      runs natively on Windows and works.
- [ ] **Unattended Gmail polling.** `ingest-gmail poll` (APScheduler `BlockingScheduler`)
      exists in code but nothing runs it unattended today — the dashboard's manual refresh
      button and ad-hoc `ingest-gmail run-once` are the only ways it currently runs. Wire to
      Windows Task Scheduler for local use, or fold into the eventual Docker deployment.
- [ ] **Gmail OAuth re-verification.** The client stays in Google's "Testing" publishing
      status — confirm the user's own email is added as a **Test user** on the consent
      screen (avoids refresh tokens expiring after 7 days regardless of activity); re-check
      Google's current policy on unverified-app refresh-token lifetime periodically.
- [ ] **Delete/edit UI for leads and interview events.** No delete button exists yet anywhere
      in the dashboard (test leads and any bad `gmail_parsed` events currently need a manual
      `psql DELETE`). Low effort, purely additive — worth doing whenever it becomes
      annoying enough, not urgent.
- [ ] **Multi-user auth**, if this ever stops being single-user: today's login is one
      `DASHBOARD_PASSWORD` env var, `hmac.compare_digest`, no `users` table, no password
      hashing — explicitly documented in `services/api/app/security.py` as *only* correct
      for exactly one operator. Do not extend the current pattern past that; replace it with
      a real `users` table + a hashing library instead.
- [ ] **`agent_runs`-style audit table for `ingest_gmail`.** Today a sync run just logs to
      stdout; no run-history table exists (the `agent_runs` table in the Data model sketch
      is scoped to Phase 4's auto-apply agent, not ingestion runs). Worth adding once the
      dashboard needs to show "last synced at" / run history somewhere, not before.
