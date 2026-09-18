from __future__ import annotations

import base64

import pytest
from googleapiclient.errors import HttpError
from jobsearch_db.models import EmailMessage, EmailThread, InterviewEvent, Lead
from sqlalchemy import select

from ingest_gmail import sync as sync_module
from ingest_gmail.classify import EmailClassification


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def _make_full_message(msg_id, thread_id, history_id, subject, from_addr, body, internal_date_ms="1758000000000"):
    return {
        "id": msg_id,
        "threadId": thread_id,
        "historyId": str(history_id),
        "internalDate": internal_date_ms,
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": from_addr},
                {"name": "Subject", "value": subject},
            ],
            "body": {"data": _b64(body)},
        },
    }


class _Exec:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class _RaisingExec:
    def __init__(self, error: Exception):
        self._error = error

    def execute(self):
        raise self._error


class _FakeMessagesResource:
    def __init__(self, messages_by_id: dict, list_page: dict):
        self._messages_by_id = messages_by_id
        self._list_page = list_page
        self.list_calls = 0

    def get(self, userId, id, format):
        return _Exec(self._messages_by_id[id])

    def list(self, userId, q=None, pageToken=None):
        self.list_calls += 1
        return _Exec(self._list_page)


class _FakeHistoryResource:
    def __init__(self, page_or_error):
        self._page_or_error = page_or_error
        self.list_calls = 0

    def list(self, userId, startHistoryId, historyTypes, pageToken=None):
        self.list_calls += 1
        if isinstance(self._page_or_error, Exception):
            return _RaisingExec(self._page_or_error)
        return _Exec(self._page_or_error)


class _FakeUsers:
    def __init__(self, messages_resource, history_resource):
        self._messages = messages_resource
        self._history = history_resource

    def messages(self):
        return self._messages

    def history(self):
        return self._history


class _FakeGmailService:
    def __init__(self, messages_resource, history_resource):
        self._users = _FakeUsers(messages_resource, history_resource)

    def users(self):
        return self._users


def _http_error_404() -> HttpError:
    resp = type("Resp", (), {"status": 404, "reason": "Not Found"})()
    return HttpError(resp, b"Not Found")


@pytest.fixture
def counting_classify(monkeypatch):
    calls: list[dict] = []

    def _fake_classify(*, subject, from_addr, body_text):
        calls.append({"subject": subject, "from_addr": from_addr, "body_text": body_text})
        return EmailClassification(
            is_job_lead=True,
            company="Acme Corp",
            role_title="Backend Engineer",
            location="Atlanta, GA",
            location_ok=True,
            confidence=0.9,
            reason="Recruiter outreach.",
        )

    monkeypatch.setattr(sync_module, "classify_email", _fake_classify)
    return calls


def test_full_resync_when_no_cursor_creates_lead(db, monkeypatch, counting_classify):
    msg = _make_full_message(
        "m1", "t1", 100, "Interview scheduled", "recruiter@greenhouse.io", "Let's talk about the role."
    )
    messages = _FakeMessagesResource({"m1": msg}, {"messages": [{"id": "m1"}]})
    history = _FakeHistoryResource({"history": []})
    monkeypatch.setattr(
        sync_module, "get_gmail_service", lambda: _FakeGmailService(messages, history)
    )

    stats = sync_module.run_once()

    assert stats.total == 1
    assert stats.leads_created == 1
    assert stats.classified == 1
    assert len(counting_classify) == 1

    lead = db.execute(select(Lead).where(Lead.source == "gmail")).scalar_one()
    assert lead.company == "Acme Corp"
    assert lead.resume_job_slug  # tailor_lead() does Path(...) / slug -- must not be None
    thread = db.execute(select(EmailThread).where(EmailThread.gmail_thread_id == "t1")).scalar_one()
    assert thread.gmail_history_id == 100
    assert thread.lead_id == lead.id


def test_rerun_is_idempotent(db, monkeypatch, counting_classify):
    # Force both calls through the full-resync path (the case that actually re-walks
    # already-seen messages -- e.g. a repeatedly stale/expired history cursor) rather than
    # relying on incremental sync's own "nothing new" behavior, which wouldn't exercise the
    # gmail_message_id idempotency guard this test is meant to prove.
    monkeypatch.setattr(sync_module, "_get_cursor", lambda db: None)

    msg = _make_full_message(
        "m1", "t1", 100, "Interview scheduled", "recruiter@greenhouse.io", "Let's talk about the role."
    )
    messages = _FakeMessagesResource({"m1": msg}, {"messages": [{"id": "m1"}]})
    history = _FakeHistoryResource({"history": []})
    monkeypatch.setattr(
        sync_module, "get_gmail_service", lambda: _FakeGmailService(messages, history)
    )

    first = sync_module.run_once()
    second = sync_module.run_once()

    assert first.leads_created == 1
    assert second.leads_created == 0
    assert second.skipped_existing == second.total == 1
    assert len(counting_classify) == 1  # no second Claude call on the re-run

    lead_count = db.execute(select(Lead)).scalars().all()
    assert len(lead_count) == 1


def test_prefiltered_message_never_reaches_classifier(db, monkeypatch, counting_classify):
    msg = _make_full_message(
        "m1", "t1", 100, "Weekly digest", "news@randomblog.com", "Check out our latest posts!"
    )
    messages = _FakeMessagesResource({"m1": msg}, {"messages": [{"id": "m1"}]})
    history = _FakeHistoryResource({"history": []})
    monkeypatch.setattr(
        sync_module, "get_gmail_service", lambda: _FakeGmailService(messages, history)
    )

    stats = sync_module.run_once()

    assert stats.prefiltered == 1
    assert stats.classified == 0
    assert len(counting_classify) == 0

    email_message = db.execute(select(EmailMessage)).scalar_one()
    assert email_message.classification == "skipped_prefilter"


def test_below_threshold_confidence_does_not_create_lead(db, monkeypatch):
    msg = _make_full_message(
        "m1", "t1", 100, "Interview scheduled", "recruiter@greenhouse.io", "Let's talk about the role."
    )
    messages = _FakeMessagesResource({"m1": msg}, {"messages": [{"id": "m1"}]})
    history = _FakeHistoryResource({"history": []})
    monkeypatch.setattr(
        sync_module, "get_gmail_service", lambda: _FakeGmailService(messages, history)
    )
    monkeypatch.setattr(
        sync_module,
        "classify_email",
        lambda **kwargs: EmailClassification(
            is_job_lead=True, company="Acme", role_title="Eng", confidence=0.3, reason="unsure"
        ),
    )

    stats = sync_module.run_once()

    assert stats.leads_created == 0
    assert db.execute(select(Lead)).scalar_one_or_none() is None
    email_message = db.execute(select(EmailMessage)).scalar_one()
    assert email_message.classification == "job_lead"
    assert email_message.classification_confidence == 0.3


def test_location_mismatch_does_not_create_lead(db, monkeypatch):
    msg = _make_full_message(
        "m1",
        "t1",
        100,
        "Great opportunity in Iowa",
        "recruiter@steneral.com",
        "Onsite role in Des Moines, IA.",
    )
    messages = _FakeMessagesResource({"m1": msg}, {"messages": [{"id": "m1"}]})
    history = _FakeHistoryResource({"history": []})
    monkeypatch.setattr(
        sync_module, "get_gmail_service", lambda: _FakeGmailService(messages, history)
    )
    monkeypatch.setattr(
        sync_module,
        "classify_email",
        lambda **kwargs: EmailClassification(
            is_job_lead=True,
            company="Steneral Consulting",
            role_title="Embedded Software Engineer",
            location="Des Moines, IA -- Onsite",
            location_ok=False,
            confidence=0.95,
            reason="Real lead, but onsite outside the target area.",
        ),
    )

    stats = sync_module.run_once()

    assert stats.classified == 1
    assert stats.leads_created == 0
    assert stats.filtered_by_location == 1
    assert db.execute(select(Lead)).scalar_one_or_none() is None

    email_message = db.execute(select(EmailMessage)).scalar_one()
    assert email_message.classification == "job_lead"
    assert email_message.location == "Des Moines, IA -- Onsite"
    assert email_message.location_ok is False


def test_expired_history_cursor_falls_back_to_full_resync(db, monkeypatch, counting_classify):
    # Seed an existing thread so _get_cursor returns a non-null cursor.
    db.add(EmailThread(gmail_thread_id="t0", gmail_history_id=50))
    db.commit()

    msg = _make_full_message(
        "m1", "t1", 100, "Interview scheduled", "recruiter@greenhouse.io", "Let's talk about the role."
    )
    messages = _FakeMessagesResource({"m1": msg}, {"messages": [{"id": "m1"}]})
    history = _FakeHistoryResource(_http_error_404())
    monkeypatch.setattr(
        sync_module, "get_gmail_service", lambda: _FakeGmailService(messages, history)
    )

    stats = sync_module.run_once()

    assert history.list_calls == 1
    assert messages.list_calls == 1  # fell back to messages().list() full resync
    assert stats.leads_created == 1


def test_lead_received_at_reflects_earliest_thread_message(db, monkeypatch):
    # A full resync doesn't guarantee chronological order; the chit-chat message here is
    # older but gets prefiltered (never creates the lead) -- the lead should still pick up
    # its received_at, not the newer message's that actually triggers creation.
    older = _make_full_message(
        "m-older",
        "t1",
        100,
        "Just checking in",
        "someone@example.com",
        "Hey, hope you're doing well!",
        internal_date_ms="1758000000000",
    )
    newer = _make_full_message(
        "m-newer",
        "t1",
        101,
        "Interview opportunity",
        "recruiter@greenhouse.io",
        "We have a role for you in Atlanta!",
        internal_date_ms="1758100000000",
    )
    messages = _FakeMessagesResource(
        {"m-older": older, "m-newer": newer},
        {"messages": [{"id": "m-older"}, {"id": "m-newer"}]},
    )
    history = _FakeHistoryResource({"history": []})
    monkeypatch.setattr(
        sync_module, "get_gmail_service", lambda: _FakeGmailService(messages, history)
    )
    monkeypatch.setattr(
        sync_module,
        "classify_email",
        lambda **kwargs: EmailClassification(
            is_job_lead=True,
            company="Acme",
            role_title="Eng",
            location="Atlanta, GA",
            location_ok=True,
            confidence=0.9,
            reason="Real lead.",
        ),
    )

    stats = sync_module.run_once()

    assert stats.prefiltered == 1  # the chit-chat message never reaches the classifier
    assert stats.leads_created == 1

    lead = db.execute(select(Lead)).scalar_one()
    older_message = db.execute(
        select(EmailMessage).where(EmailMessage.gmail_message_id == "m-older")
    ).scalar_one()
    newer_message = db.execute(
        select(EmailMessage).where(EmailMessage.gmail_message_id == "m-newer")
    ).scalar_one()
    # Compare against the DB-round-tripped values (not a fresh _parse_internal_date() call)
    # since Postgres converts an aware UTC datetime to naive-local on the way in.
    assert lead.received_at == older_message.received_at
    assert lead.received_at != newer_message.received_at


def test_interview_event_created_for_new_lead(db, monkeypatch):
    msg = _make_full_message(
        "m1", "t1", 100, "Interview confirmed", "recruiter@greenhouse.io", "Let's meet."
    )
    messages = _FakeMessagesResource({"m1": msg}, {"messages": [{"id": "m1"}]})
    history = _FakeHistoryResource({"history": []})
    monkeypatch.setattr(
        sync_module, "get_gmail_service", lambda: _FakeGmailService(messages, history)
    )
    monkeypatch.setattr(
        sync_module,
        "classify_email",
        lambda **kwargs: EmailClassification(
            is_job_lead=True,
            company="Acme",
            role_title="Eng",
            location="Remote",
            location_ok=True,
            interview_mentioned=True,
            interview_datetime="2026-09-25T14:00:00-04:00",
            interview_type="phone_screen",
            interview_location_or_link="https://zoom.us/j/12345",
            interview_confidence=0.9,
            confidence=0.95,
            reason="Phone screen confirmed for Sep 25 at 2pm ET.",
        ),
    )

    stats = sync_module.run_once()

    assert stats.interview_events_created == 1
    event = db.execute(select(InterviewEvent)).scalar_one()
    assert event.event_type == "phone_screen"
    assert event.location_or_link == "https://zoom.us/j/12345"
    assert event.source == "gmail_parsed"
    lead = db.execute(select(Lead)).scalar_one()
    assert event.lead_id == lead.id


def test_interview_event_attached_to_existing_lead_from_ambiguous_reply(db, monkeypatch):
    # First message creates the lead. Second message (a short reply that doesn't look like
    # a job lead on its own) still carries a confirmed interview date and should attach to
    # the thread's already-existing lead, not be dropped for lacking its own is_job_lead=true.
    first = _make_full_message(
        "m1", "t1", 100, "Interview opportunity", "recruiter@greenhouse.io", "Interested?"
    )
    second = _make_full_message(
        "m2", "t1", 101, "Re: Interview opportunity", "recruiter@greenhouse.io", "Confirmed for Thursday."
    )
    messages = _FakeMessagesResource(
        {"m1": first, "m2": second}, {"messages": [{"id": "m1"}, {"id": "m2"}]}
    )
    history = _FakeHistoryResource({"history": []})
    monkeypatch.setattr(
        sync_module, "get_gmail_service", lambda: _FakeGmailService(messages, history)
    )

    def _fake_classify(*, subject, from_addr, body_text):
        if subject.startswith("Re:"):
            return EmailClassification(
                is_job_lead=False,
                interview_mentioned=True,
                interview_datetime="2026-09-25T14:00:00-04:00",
                interview_type="call",
                interview_confidence=0.85,
                confidence=0.4,
                reason="Short confirmation reply, not independently a job lead.",
            )
        return EmailClassification(
            is_job_lead=True,
            company="Acme",
            role_title="Eng",
            location="Remote",
            location_ok=True,
            confidence=0.9,
            reason="Recruiter outreach.",
        )

    monkeypatch.setattr(sync_module, "classify_email", _fake_classify)

    stats = sync_module.run_once()

    assert stats.leads_created == 1
    assert stats.interview_events_created == 1
    lead = db.execute(select(Lead)).scalar_one()
    event = db.execute(select(InterviewEvent)).scalar_one()
    assert event.lead_id == lead.id
    assert event.event_type == "call"


def test_interview_event_dedup_same_datetime(db, monkeypatch):
    first = _make_full_message(
        "m1", "t1", 100, "Interview invite", "recruiter@greenhouse.io", "Invite attached."
    )
    second = _make_full_message(
        "m2", "t1", 101, "Re: Interview invite", "recruiter@greenhouse.io", "Confirmed!"
    )
    messages = _FakeMessagesResource(
        {"m1": first, "m2": second}, {"messages": [{"id": "m1"}, {"id": "m2"}]}
    )
    history = _FakeHistoryResource({"history": []})
    monkeypatch.setattr(
        sync_module, "get_gmail_service", lambda: _FakeGmailService(messages, history)
    )
    monkeypatch.setattr(
        sync_module,
        "classify_email",
        lambda **kwargs: EmailClassification(
            is_job_lead=True,
            company="Acme",
            role_title="Eng",
            location="Remote",
            location_ok=True,
            interview_mentioned=True,
            interview_datetime="2026-09-25T14:00:00-04:00",
            interview_type="call",
            interview_confidence=0.9,
            confidence=0.9,
            reason="Same interview mentioned twice.",
        ),
    )

    stats = sync_module.run_once()

    assert stats.interview_events_created == 1  # not 2 -- same lead, same datetime
    events = db.execute(select(InterviewEvent)).scalars().all()
    assert len(events) == 1


def test_interview_event_skipped_below_confidence(db, monkeypatch):
    msg = _make_full_message(
        "m1", "t1", 100, "Interview maybe", "recruiter@greenhouse.io", "Maybe Thursday?"
    )
    messages = _FakeMessagesResource({"m1": msg}, {"messages": [{"id": "m1"}]})
    history = _FakeHistoryResource({"history": []})
    monkeypatch.setattr(
        sync_module, "get_gmail_service", lambda: _FakeGmailService(messages, history)
    )
    monkeypatch.setattr(
        sync_module,
        "classify_email",
        lambda **kwargs: EmailClassification(
            is_job_lead=True,
            company="Acme",
            role_title="Eng",
            location="Remote",
            location_ok=True,
            interview_mentioned=True,
            interview_datetime="2026-09-25T14:00:00-04:00",
            interview_type="call",
            interview_confidence=0.4,
            confidence=0.9,
            reason="Vague, low-confidence date mention.",
        ),
    )

    stats = sync_module.run_once()

    assert stats.leads_created == 1
    assert stats.interview_events_created == 0
    assert db.execute(select(InterviewEvent)).scalar_one_or_none() is None
