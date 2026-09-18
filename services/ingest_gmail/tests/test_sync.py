from __future__ import annotations

import base64

import pytest
from googleapiclient.errors import HttpError
from jobsearch_db.models import EmailMessage, EmailThread, Lead
from sqlalchemy import select

from ingest_gmail import sync as sync_module
from ingest_gmail.classify import EmailClassification


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def _make_full_message(msg_id, thread_id, history_id, subject, from_addr, body):
    return {
        "id": msg_id,
        "threadId": thread_id,
        "historyId": str(history_id),
        "internalDate": "1758000000000",
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
