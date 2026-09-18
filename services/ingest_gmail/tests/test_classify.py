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
        "confidence": 0.91,
        "reason": "Recruiter outreach about a specific open role.",
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
    assert result.confidence == 0.91
    assert fake_client_factory.messages.last_kwargs["tool_choice"] == {
        "type": "tool",
        "name": classify_module.TOOL_NAME,
    }


def test_classify_email_not_a_lead(monkeypatch):
    payload = {
        "is_job_lead": False,
        "company": None,
        "role_title": None,
        "confidence": 0.2,
        "reason": "Marketing newsletter, not a specific opportunity.",
    }
    monkeypatch.setattr(classify_module.anthropic, "Anthropic", _FakeAnthropic(payload))

    result = classify_email(subject="Digest", from_addr="news@example.com", body_text="...")

    assert result.is_job_lead is False
    assert result.company is None
