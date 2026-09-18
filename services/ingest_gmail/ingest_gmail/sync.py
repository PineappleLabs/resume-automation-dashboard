from __future__ import annotations

import base64
import datetime as dt
import logging
import re
from dataclasses import dataclass

from googleapiclient.errors import HttpError
from jobsearch_db.db import SessionLocal
from jobsearch_db.models import (
    INTERVIEW_TYPES,
    EmailMessage,
    EmailThread,
    InterviewEvent,
    Lead,
    StatusHistory,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .classify import EmailClassification, classify_email
from .config import settings
from .gmail_auth import get_gmail_service
from .prefilter import passes_prefilter
from .slugs import unique_lead_slug

logger = logging.getLogger(__name__)


@dataclass
class SyncStats:
    total: int = 0
    skipped_existing: int = 0
    prefiltered: int = 0
    classified: int = 0
    leads_created: int = 0
    filtered_by_location: int = 0
    interview_events_created: int = 0


def _get_cursor(db: Session) -> int | None:
    return db.execute(select(func.max(EmailThread.gmail_history_id))).scalar()


def _list_incremental(service, start_history_id: int) -> list[dict]:
    refs: list[dict] = []
    page_token = None
    while True:
        resp = (
            service.users()
            .history()
            .list(
                userId="me",
                startHistoryId=str(start_history_id),
                historyTypes=["messageAdded"],
                pageToken=page_token,
            )
            .execute()
        )
        for record in resp.get("history", []):
            for added in record.get("messagesAdded", []):
                refs.append(added["message"])
        page_token = resp.get("nextPageToken")
        if not page_token:
            return refs


def _list_full_resync(service, days: int) -> list[dict]:
    refs: list[dict] = []
    page_token = None
    while True:
        resp = (
            service.users()
            .messages()
            .list(userId="me", q=f"newer_than:{days}d", pageToken=page_token)
            .execute()
        )
        refs.extend(resp.get("messages", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            return refs


def _decode_b64url(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def _extract_plain_text(payload: dict) -> str:
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return _decode_b64url(payload["body"]["data"])
    for part in payload.get("parts", []) or []:
        text = _extract_plain_text(part)
        if text:
            return text
    if payload.get("mimeType") == "text/html" and payload.get("body", {}).get("data"):
        return re.sub(r"<[^>]+>", " ", _decode_b64url(payload["body"]["data"]))
    return ""


def _parse_internal_date(internal_date: str | None) -> dt.datetime | None:
    if not internal_date:
        return None
    return dt.datetime.fromtimestamp(int(internal_date) / 1000, tz=dt.timezone.utc)


def _parse_interview_datetime(value: str) -> dt.datetime | None:
    """Parse the classifier's ISO 8601 string into a naive local datetime.

    interview_events.scheduled_at is stored naive everywhere else (the manual add-event
    form is a browser datetime-local input with no timezone), so a timezone-aware result
    here is converted to the system's local time and stripped, to match.
    """
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        logger.warning("Could not parse interview_datetime %r from classifier", value)
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def _earliest_received_at(db: Session, thread_id: int, fallback: dt.datetime | None) -> dt.datetime | None:
    """The thread's oldest known message time, so a lead's received_at reflects when the
    conversation actually started -- not whichever message happened to trigger lead
    creation. A full resync can process a thread's messages out of chronological order
    (Gmail's messages.list is not guaranteed newest-last), so this can't just use the
    current message's own timestamp.
    """
    earliest = db.execute(
        select(func.min(EmailMessage.received_at)).where(EmailMessage.thread_id == thread_id)
    ).scalar()
    return earliest or fallback


def _upsert_lead(
    db: Session,
    thread: EmailThread,
    result: EmailClassification,
    from_addr: str,
    body_text: str,
    received_at: dt.datetime | None,
) -> tuple[Lead, bool]:
    existing = db.execute(
        select(Lead).where(Lead.source == "gmail", Lead.source_ref == thread.gmail_thread_id)
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    db.flush()  # make this message's just-added EmailMessage row visible to the query below
    lead = Lead(
        company=result.company or "Unknown",
        role_title=result.role_title or "Unknown",
        source="gmail",
        source_ref=thread.gmail_thread_id,
        jd_text=body_text,
        recruiter_contact=from_addr,
        received_at=_earliest_received_at(db, thread.id, received_at),
        status="new",
    )
    db.add(lead)
    db.flush()
    lead.resume_job_slug = unique_lead_slug(db, lead.company, lead.role_title)
    thread.lead_id = lead.id
    db.add(
        StatusHistory(
            lead_id=lead.id,
            old_status=None,
            new_status="new",
            changed_by="system",
            confidence=result.confidence,
            reason=f"Classified from Gmail thread {thread.gmail_thread_id}: {result.reason}",
        )
    )
    return lead, True


def _create_interview_event(
    db: Session, lead: Lead, result: EmailClassification, scheduled_at: dt.datetime
) -> bool:
    """Returns False (no-op) if an event at this exact time already exists on the lead --
    an invite followed by a "confirmed!" reply both mentioning the same time shouldn't
    create two events.
    """
    db.flush()  # autoflush is off; make any earlier-in-this-run InterviewEvent visible
    existing = db.execute(
        select(InterviewEvent.id).where(
            InterviewEvent.lead_id == lead.id, InterviewEvent.scheduled_at == scheduled_at
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False

    event_type = result.interview_type if result.interview_type in INTERVIEW_TYPES else "other"
    db.add(
        InterviewEvent(
            lead_id=lead.id,
            scheduled_at=scheduled_at,
            event_type=event_type,
            location_or_link=result.interview_location_or_link,
            notes=f"Parsed from Gmail: {result.reason}",
            source="gmail_parsed",
        )
    )
    return True


def _process_message(
    db: Session,
    service,
    ref: dict,
    threshold: float,
    interview_threshold: float,
    stats: SyncStats,
) -> None:
    gmail_message_id = ref["id"]
    if db.execute(
        select(EmailMessage.id).where(EmailMessage.gmail_message_id == gmail_message_id)
    ).scalar_one_or_none():
        stats.skipped_existing += 1
        return

    full = service.users().messages().get(userId="me", id=gmail_message_id, format="full").execute()
    thread_gid = full["threadId"]
    history_id = int(full["historyId"])
    headers = {h["name"].lower(): h["value"] for h in full["payload"].get("headers", [])}
    from_addr = headers.get("from", "")
    subject = headers.get("subject", "")
    body_text = _extract_plain_text(full["payload"])
    received_at = _parse_internal_date(full.get("internalDate"))

    thread = db.execute(
        select(EmailThread).where(EmailThread.gmail_thread_id == thread_gid)
    ).scalar_one_or_none()
    if thread is None:
        thread = EmailThread(gmail_thread_id=thread_gid)
        db.add(thread)
        db.flush()
    thread.gmail_history_id = max(thread.gmail_history_id or 0, history_id)
    thread.last_message_id = gmail_message_id
    thread.last_synced_at = dt.datetime.now(dt.timezone.utc)

    if not passes_prefilter(from_addr, subject, body_text):
        db.add(
            EmailMessage(
                thread_id=thread.id,
                gmail_message_id=gmail_message_id,
                from_addr=from_addr,
                subject=subject,
                body_text=body_text,
                received_at=received_at,
                direction="inbound",
                classification="skipped_prefilter",
            )
        )
        stats.prefiltered += 1
        return

    result = classify_email(subject=subject, from_addr=from_addr, body_text=body_text)
    db.add(
        EmailMessage(
            thread_id=thread.id,
            gmail_message_id=gmail_message_id,
            from_addr=from_addr,
            subject=subject,
            body_text=body_text,
            received_at=received_at,
            direction="inbound",
            classification="job_lead" if result.is_job_lead else "not_job_lead",
            classification_confidence=result.confidence,
            location=result.location,
            location_ok=result.location_ok,
        )
    )
    stats.classified += 1

    lead: Lead | None = None
    if result.is_job_lead and result.confidence >= threshold:
        if result.location_ok:
            lead, created = _upsert_lead(db, thread, result, from_addr, body_text, received_at)
            if created:
                stats.leads_created += 1
        else:
            stats.filtered_by_location += 1

    if lead is None and thread.lead_id is not None:
        lead = db.get(Lead, thread.lead_id)

    if (
        lead is not None
        and result.interview_mentioned
        and result.interview_datetime
        and result.interview_confidence >= interview_threshold
    ):
        scheduled_at = _parse_interview_datetime(result.interview_datetime)
        if scheduled_at is not None and _create_interview_event(db, lead, result, scheduled_at):
            stats.interview_events_created += 1


def run_once(
    *,
    confidence_threshold: float | None = None,
    interview_confidence_threshold: float | None = None,
    full_resync_days: int | None = None,
) -> SyncStats:
    threshold = confidence_threshold if confidence_threshold is not None else (
        settings.classification_confidence_threshold
    )
    interview_threshold = (
        interview_confidence_threshold
        if interview_confidence_threshold is not None
        else settings.interview_confidence_threshold
    )
    days = full_resync_days or settings.full_resync_days
    service = get_gmail_service()
    stats = SyncStats()

    with SessionLocal() as db:
        cursor = _get_cursor(db)
        if cursor is None:
            refs = _list_full_resync(service, days)
        else:
            try:
                refs = _list_incremental(service, cursor)
            except HttpError as exc:
                if exc.resp.status == 404:
                    logger.warning("Gmail history cursor %s expired/invalid; full resync", cursor)
                    refs = _list_full_resync(service, days)
                else:
                    raise

        stats.total = len(refs)
        for ref in refs:
            _process_message(db, service, ref, threshold, interview_threshold, stats)
        db.commit()

    return stats
