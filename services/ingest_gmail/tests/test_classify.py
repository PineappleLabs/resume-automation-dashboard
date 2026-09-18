from __future__ import annotations

from ingest_gmail import classify as classify_module
from ingest_gmail.classify import classify_email


class _FakeToolUseBlock:
    type = "tool_use"
    name = classify_module.TOOL_NAME

    def __init__(self, input_data: dict) -> None:
        self.input = input_data


class _FakeMessage:
    def __init__(self, input_data: dict) -> None:
        self.content = [_FakeToolUseBlock(input_data)]


class _FakeMessages:
    def __init__(self, input_data: dict) -> None:
        self._input_data = input_data
        self.last_kwargs: dict | None = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return _FakeMessage(self._input_data)


class _FakeAnthropic:
    def __init__(self, input_data: dict) -> None:
        self.messages = _FakeMessages(input_data)

    def __call__(self, api_key: str):
        return self


def test_classify_email_parses_tool_response(monkeypatch):
    payload = {
        "is_job_lead": True,
        "company": "Acme Corp",
        "role_title": "Backend Engineer",
        "location": "Atlanta, GA",
        "location_ok": True,
        "confidence": 0.91,
        "reason": "Recruiter outreach about a specific open role in Atlanta.",
    }
    fake_client_factory = _FakeAnthropic(payload)
    monkeypatch.setattr(classify_module.anthropic, "Anthropic", fake_client_factory)

    result = classify_email(
        subject="Exciting opportunity at Acme",
        from_addr="recruiter@acme.com",
        body_text="We'd love to chat about our Backend Engineer role.",
    )

    assert result.is_job_lead is True
    assert result.company == "Acme Corp"
    assert result.location == "Atlanta, GA"
    assert result.location_ok is True
    assert result.confidence == 0.91
    assert fake_client_factory.messages.last_kwargs["tool_choice"] == {
        "type": "tool",
        "name": classify_module.TOOL_NAME,
    }
    assert "Atlanta" in fake_client_factory.messages.last_kwargs["system"]


def test_classify_email_not_a_lead(monkeypatch):
    payload = {
        "is_job_lead": False,
        "company": None,
        "role_title": None,
        "location": None,
        "location_ok": False,
        "confidence": 0.2,
        "reason": "Marketing newsletter, not a specific opportunity.",
    }
    monkeypatch.setattr(classify_module.anthropic, "Anthropic", _FakeAnthropic(payload))

    result = classify_email(subject="Digest", from_addr="news@example.com", body_text="...")

    assert result.is_job_lead is False
    assert result.company is None


def test_classify_email_wrong_location(monkeypatch):
    payload = {
        "is_job_lead": True,
        "company": "Steneral Consulting",
        "role_title": "Embedded Software Engineer",
        "location": "Urbandale, Des Moines, or Moline, IA -- Onsite",
        "location_ok": False,
        "confidence": 0.95,
        "reason": "Real recruiter outreach, but onsite in Iowa -- outside the target area.",
    }
    monkeypatch.setattr(classify_module.anthropic, "Anthropic", _FakeAnthropic(payload))

    result = classify_email(subject="Role in Iowa", from_addr="recruiter@steneral.com", body_text="...")

    assert result.is_job_lead is True
    assert result.location_ok is False
