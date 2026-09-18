from __future__ import annotations

from typing import Any

import anthropic
from pydantic import BaseModel, Field

from .config import settings

TOOL_NAME = "classify_email"


class EmailClassification(BaseModel):
    is_job_lead: bool
    company: str | None = None
    role_title: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


def _resolve_schema_refs(schema: dict[str, Any]) -> dict[str, Any]:
    # Copied from resume_pipeline.select._resolve_schema_refs (a private helper there) --
    # duplicated rather than imported so this worker and the pipeline package don't couple
    # over a 15-line pure function.
    defs = schema.get("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                ref_name = node["$ref"].rsplit("/", maxsplit=1)[-1]
                return resolve(defs[ref_name])
            resolved = {key: resolve(value) for key, value in node.items()}
            if resolved.get("type") == "object":
                resolved.setdefault("additionalProperties", False)
            return resolved
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    resolved = resolve(schema)
    if isinstance(resolved, dict):
        resolved.pop("$defs", None)
        if resolved.get("type") == "object":
            resolved.setdefault("additionalProperties", False)
    return resolved


def _system_prompt() -> str:
    return (
        "You are an email triage assistant for a job search. Given the subject, sender, and "
        "body of a single email, decide whether it represents a job lead: a recruiter "
        "outreach, an application status update from an ATS, or an interview/offer message.\n\n"
        "Rules:\n"
        "- Set is_job_lead=true only for emails clearly related to a specific job opportunity "
        "for this person -- not general newsletters, job-alert digests with many postings, or "
        "marketing.\n"
        "- When is_job_lead=true, extract company and role_title if identifiable from the "
        "text; leave them null if genuinely unclear rather than guessing.\n"
        "- confidence reflects how certain you are in the is_job_lead call itself (0.0-1.0).\n"
        "- reason is a one-sentence justification.\n"
        f"- Call the {TOOL_NAME} tool with your result."
    )


def _classification_tool() -> anthropic.types.ToolParam:
    return {
        "name": TOOL_NAME,
        "description": "Classify a single email as a job lead or not, with extracted fields.",
        "input_schema": _resolve_schema_refs(EmailClassification.model_json_schema()),
    }


def _extract_tool_input(response: anthropic.types.Message) -> dict[str, Any]:
    for block in response.content:
        if block.type == "tool_use" and block.name == TOOL_NAME:
            if isinstance(block.input, dict):
                return block.input
            raise RuntimeError("Claude returned a non-object tool input.")
    raise RuntimeError("Claude did not return a classify_email tool call.")


def classify_email(*, subject: str, from_addr: str, body_text: str) -> EmailClassification:
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    response = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=1024,
        system=_system_prompt(),
        messages=[
            {
                "role": "user",
                "content": f"From: {from_addr}\nSubject: {subject}\n\n{body_text[:6000]}",
            }
        ],
        tools=[_classification_tool()],
        tool_choice={"type": "tool", "name": TOOL_NAME},
    )
    return EmailClassification.model_validate(_extract_tool_input(response))
