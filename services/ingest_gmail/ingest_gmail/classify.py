from __future__ import annotations

from typing import Any

import anthropic
from jobsearch_db.models import INTERVIEW_TYPES
from pydantic import BaseModel, Field

from .config import settings

TOOL_NAME = "classify_email"


class EmailClassification(BaseModel):
    is_job_lead: bool
    company: str | None = None
    role_title: str | None = None
    location: str | None = None
    location_ok: bool = False
    interview_mentioned: bool = False
    interview_datetime: str | None = None
    interview_type: str | None = None
    interview_location_or_link: str | None = None
    interview_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
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


def _system_prompt(target_location_description: str) -> str:
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
        "- Also extract the job's location as stated in the email (e.g. city/state, "
        "'Remote', 'Hybrid - Atlanta, GA', 'Onsite - Des Moines, IA') into `location`; leave "
        "it null if the email doesn't state one.\n"
        f"- The candidate only wants roles in: {target_location_description}. Set "
        "location_ok=true only if the stated location clearly satisfies that (a hybrid role "
        "based in the target city counts; an onsite/relocation-required role elsewhere does "
        "not). If is_job_lead=false or the location is genuinely unstated/ambiguous, set "
        "location_ok=false.\n"
        "- Also decide whether THIS email states a specific interview, phone screen, or call "
        "with a concrete date and time (an invite, a confirmation, a 'let's talk Thursday at "
        "2pm' message, or a meeting link with an embedded date) -- not a vague 'let's find a "
        "time soon'. Set interview_mentioned=true only when a specific date/time is actually "
        "stated in this email.\n"
        "- When interview_mentioned=true: interview_datetime is that date/time as an ISO 8601 "
        "string (YYYY-MM-DDTHH:MM:SS, plus a UTC offset like -04:00 if the email states a "
        "timezone, otherwise omit the offset) -- infer the year from context if not stated "
        "(assume the most plausible upcoming date); interview_type is your best guess from "
        f"[{', '.join(INTERVIEW_TYPES)}]; interview_location_or_link is the meeting "
        "link/dial-in/physical location if given, else null.\n"
        "- interview_confidence reflects certainty in interview_mentioned and the extracted "
        "datetime (0.0-1.0). Leave interview_mentioned=false, interview_datetime=null, and "
        "interview_confidence=0.0 when no specific date/time is stated.\n"
        "- confidence reflects how certain you are in the is_job_lead call itself (0.0-1.0).\n"
        "- reason is a one-sentence justification covering the is_job_lead, location_ok, and "
        "interview_mentioned calls.\n"
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
        system=_system_prompt(settings.target_location_description),
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
