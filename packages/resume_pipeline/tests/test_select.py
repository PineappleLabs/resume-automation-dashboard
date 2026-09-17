from __future__ import annotations

import pytest

from resume_pipeline import select as select_module
from resume_pipeline.select import select_for_job


class _FakeToolUseBlock:
    type = "tool_use"
    name = select_module.TOOL_NAME

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


def _selection_payload(sample_content) -> dict:
    return {
        "rationale": "Picked the senior role bullets.",
        "section_order": ["education", "skills", "experience", "projects"],
        "education": [{"entry_id": "edu-1", "bullet_ids": ["edu-1-b1"]}],
        "skill_line_ids": ["skill-1"],
        "experience": [{"entry_id": "exp-1", "bullet_ids": ["exp-1-b1"]}],
        "project_ids": ["proj-1"],
        "bullet_priorities": {"exp-1-b1": 95},
    }


def test_select_for_job_parses_tool_response(monkeypatch, sample_content):
    payload = _selection_payload(sample_content)
    fake_client_factory = _FakeAnthropic(payload)
    monkeypatch.setattr(select_module.anthropic, "Anthropic", fake_client_factory)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    selection = select_for_job("A senior engineering job.", content=sample_content)

    assert selection.rationale == payload["rationale"]
    assert selection.experience[0].entry_id == "exp-1"
    assert fake_client_factory.messages.last_kwargs["tool_choice"] == {
        "type": "tool",
        "name": select_module.TOOL_NAME,
    }


def test_select_for_job_requires_api_key(monkeypatch, sample_content):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(select_module, "load_dotenv", lambda: None)

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        select_for_job("A job description.", content=sample_content)
