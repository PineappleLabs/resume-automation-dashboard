from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from jobsearch_db.models import EmailMessage, EmailThread, Lead


def _make_lead(db: Session, **overrides) -> Lead:
    defaults = dict(company="Acme", role_title="Engineer", source="manual", status="new")
    defaults.update(overrides)
    lead = Lead(**defaults)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def test_lead_status_check_constraint_rejects_invalid_value(db: Session) -> None:
    lead = Lead(company="Acme", role_title="Engineer", source="manual", status="not-a-real-status")
    db.add(lead)
    with pytest.raises(IntegrityError):
        db.commit()


def test_resume_job_slug_must_be_unique(db: Session) -> None:
    _make_lead(db, resume_job_slug="acme-engineer")
    db.add(Lead(company="Beta", role_title="Engineer", resume_job_slug="acme-engineer"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_email_thread_gmail_thread_id_unique(db: Session) -> None:
    db.add(EmailThread(gmail_thread_id="thread-1"))
    db.commit()
    db.add(EmailThread(gmail_thread_id="thread-1"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_deleting_lead_sets_email_thread_lead_id_null_not_cascade(db: Session) -> None:
    lead = _make_lead(db)
    thread = EmailThread(gmail_thread_id="thread-2", lead_id=lead.id)
    db.add(thread)
    db.commit()

    db.delete(lead)
    db.commit()

    db.refresh(thread)
    assert thread.lead_id is None


def test_deleting_thread_cascades_to_messages(db: Session) -> None:
    thread = EmailThread(gmail_thread_id="thread-3")
    db.add(thread)
    db.commit()
    db.add(
        EmailMessage(
            thread_id=thread.id,
            gmail_message_id="msg-1",
            direction="inbound",
            received_at=dt.datetime.now(dt.timezone.utc),
        )
    )
    db.commit()

    db.delete(thread)
    db.commit()

    remaining = db.query(EmailMessage).filter_by(gmail_message_id="msg-1").one_or_none()
    assert remaining is None


def test_email_message_confidence_out_of_range_rejected(db: Session) -> None:
    thread = EmailThread(gmail_thread_id="thread-4")
    db.add(thread)
    db.commit()
    db.add(
        EmailMessage(
            thread_id=thread.id,
            gmail_message_id="msg-2",
            direction="inbound",
            classification="job_lead",
            classification_confidence=1.5,
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
