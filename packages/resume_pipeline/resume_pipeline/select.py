from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import anthropic
from dotenv import load_dotenv

from .render import load_content
from .schema import ResumeContent, Selection, SelectionResponse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = "claude-sonnet-5"
TOOL_NAME = "resume_selection"


def _inventory(content: ResumeContent) -> str:
    lines: list[str] = []

    lines.append("## Education")
    for entry in content.education:
        lines.append(
            f"- {entry.id}: {entry.organization}, {entry.title} ({entry.dates}) "
            f"[tags: {', '.join(entry.tags)}]"
        )
        if entry.summary:
            lines.append(f"  summary: {entry.summary}")
        for bullet in entry.bullets:
            summary = bullet.summary or bullet.text[:120]
            lines.append(
                f"  - {bullet.id} [priority {bullet.priority}, tags: {', '.join(bullet.tags)}]: "
                f"{summary}"
            )

    lines.append("\n## Skills")
    for line in content.skills:
        summary = line.summary or line.text[:120]
        lines.append(
            f"- {line.id} [priority {line.priority}, tags: {', '.join(line.tags)}]: {summary}"
        )

    lines.append("\n## Experience")
    for entry in content.experience:
        lines.append(
            f"- {entry.id}: {entry.organization}, {entry.title} ({entry.dates}) "
            f"[tags: {', '.join(entry.tags)}]"
        )
        if entry.summary:
            lines.append(f"  summary: {entry.summary}")
        for bullet in entry.bullets:
            summary = bullet.summary or bullet.text[:120]
            lines.append(
                f"  - {bullet.id} [priority {bullet.priority}, tags: {', '.join(bullet.tags)}]: "
                f"{summary}"
            )

    lines.append("\n## Projects")
    for project in content.projects:
        summary = project.summary or project.text[:120]
        lines.append(
            f"- {project.id} [priority {project.priority}, tags: {', '.join(project.tags)}]: "
            f"{summary}"
        )

    return "\n".join(lines)


def _system_prompt() -> str:
    return (
        "You are a resume tailoring assistant. Given a job description and an inventory of "
        "resume content IDs, select the most relevant content for a one-page resume.\n\n"
        "Rules:\n"
        "- Selection only: choose existing IDs verbatim. Do NOT rewrite bullet text.\n"
        "- Include the most relevant experience, projects, skills, and education for the role.\n"
        "- Prefer recent and directly applicable experience.\n"
        "- Assign bullet_priorities (0-100) where higher means more important to keep on a "
        "one-page resume. Pinned items should receive high priorities.\n"
        "- Order sections as education, skills, experience, projects unless the role strongly "
        "favors another order.\n"
        "- For each education and experience entry, include at least one bullet.\n"
        "- Include 2-4 projects when relevant; fewer for senior roles focused on experience.\n"
        "- Include all three skill lines unless space is tight; drop skills-creative first.\n"
        "- Return only IDs that exist in the inventory.\n"
        f"- Call the {TOOL_NAME} tool with your final selection."
    )


def _resolve_schema_refs(schema: dict[str, Any]) -> dict[str, Any]:
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


def _selection_tool() -> anthropic.types.ToolParam:
    input_schema = _resolve_schema_refs(SelectionResponse.model_json_schema())
    return {
        "name": TOOL_NAME,
        "description": (
            "Return the selected resume content IDs, section order, and bullet priorities "
            "for a one-page tailored resume."
        ),
        "input_schema": input_schema,
    }


def _extract_tool_input(response: anthropic.types.Message) -> dict[str, Any]:
    for block in response.content:
        if block.type == "tool_use" and block.name == TOOL_NAME:
            if isinstance(block.input, dict):
                return block.input
            raise RuntimeError("Claude returned a non-object tool input.")
    raise RuntimeError("Claude did not return a resume selection tool call.")


def select_for_job(
    job_description: str,
    content: ResumeContent | None = None,
    model: str | None = None,
) -> Selection:
    load_dotenv()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key."
        )

    content = content or load_content()
    client = anthropic.Anthropic(api_key=api_key)
    model_name = model or os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)

    response = client.messages.create(
        model=model_name,
        max_tokens=4096,
        system=_system_prompt(),
        messages=[
            {
                "role": "user",
                "content": (
                    f"Job description:\n\n{job_description}\n\n"
                    f"Content inventory:\n\n{_inventory(content)}"
                ),
            }
        ],
        tools=[_selection_tool()],
        tool_choice={"type": "tool", "name": TOOL_NAME},
    )

    parsed = SelectionResponse.model_validate(_extract_tool_input(response))
    return Selection.model_validate(parsed.model_dump())


def save_selection(selection: Selection, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(selection.model_dump(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def load_selection(path: Path) -> Selection:
    data = json.loads(path.read_text(encoding="utf-8"))
    return Selection.model_validate(data)
