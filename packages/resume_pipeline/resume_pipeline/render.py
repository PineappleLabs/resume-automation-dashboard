from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pypdf import PdfReader

from .schema import (
    Bullet,
    EducationEntry,
    EntrySelection,
    ExperienceEntry,
    ProjectEntry,
    ResumeContent,
    Selection,
    SkillLine,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONTENT_PATH = PROJECT_ROOT / "content" / "content.yaml"
TEMPLATE_DIR = PROJECT_ROOT / "templates"
PREAMBLE_PATH = TEMPLATE_DIR / "preamble.tex"


def load_content(path: Path | None = None) -> ResumeContent:
    content_path = path or CONTENT_PATH
    with content_path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return ResumeContent.model_validate(data)


_TECTONIC_PATH: str | None = None

# fit_to_one_page() calls compile_pdf() once per dropped/restored bullet, so
# _find_tectonic() can run dozens of times in a single `tailor` invocation.
# The executable's location never changes mid-run, so resolve it once and
# reuse the cached path instead of re-walking PATH and the fallback
# candidates on every compile.
def _find_tectonic() -> str:
    global _TECTONIC_PATH
    if _TECTONIC_PATH is not None:
        return _TECTONIC_PATH

    candidates = [
        shutil.which("tectonic"),
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "tectonic" / "tectonic.exe"),
        str(Path.home() / ".local" / "bin" / "tectonic"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            _TECTONIC_PATH = candidate
            return candidate
    raise FileNotFoundError(
        "Tectonic not found. Install from https://tectonic-typesetting.github.io/ "
        "or add tectonic.exe to PATH."
    )


def default_priorities(content: ResumeContent) -> dict[str, int]:
    priorities: dict[str, int] = {}
    for entry in content.education:
        for bullet in entry.bullets:
            priorities[bullet.id] = bullet.priority
    for entry in content.experience:
        for bullet in entry.bullets:
            priorities[bullet.id] = bullet.priority
    for project in content.projects:
        priorities[project.id] = project.priority
    for line in content.skills:
        priorities[line.id] = line.priority
    return priorities


def _priority_map(selection: Selection, content: ResumeContent) -> dict[str, int]:
    priorities = default_priorities(content)
    priorities.update(selection.bullet_priorities)
    return priorities


def _pinned_map(content: ResumeContent) -> dict[str, bool]:
    pinned: dict[str, bool] = {}
    for entry in content.education:
        for bullet in entry.bullets:
            pinned[bullet.id] = bullet.pinned or entry.pinned
    for entry in content.experience:
        for bullet in entry.bullets:
            pinned[bullet.id] = bullet.pinned or entry.pinned
    for project in content.projects:
        pinned[project.id] = project.pinned
    for line in content.skills:
        pinned[line.id] = line.pinned
    return pinned


def master_selection(content: ResumeContent) -> Selection:
    return Selection(
        rationale="Master resume including all content.",
        section_order=["education", "skills", "experience", "projects"],
        education=[
            EntrySelection(
                entry_id=entry.id,
                bullet_ids=[bullet.id for bullet in entry.bullets],
            )
            for entry in content.education
        ],
        skill_line_ids=[line.id for line in content.skills],
        experience=[
            EntrySelection(
                entry_id=entry.id,
                bullet_ids=[bullet.id for bullet in entry.bullets],
            )
            for entry in content.experience
        ],
        project_ids=[project.id for project in content.projects],
        bullet_priorities=default_priorities(content),
    )


def _resolve_bullets(
    entry_bullets: list[Bullet], bullet_ids: list[str]
) -> list[Bullet]:
    lookup = {bullet.id: bullet for bullet in entry_bullets}
    return [lookup[bullet_id] for bullet_id in bullet_ids if bullet_id in lookup]


def build_render_context(content: ResumeContent, selection: Selection) -> dict:
    education_by_id = {entry.id: entry for entry in content.education}
    skills_by_id = {line.id: line for line in content.skills}
    experience_by_id = {entry.id: entry for entry in content.experience}
    projects_by_id = {project.id: project for project in content.projects}

    # content.yaml lists each section in reverse-chronological (most recent
    # first) order. Selections may reorder entries by relevance, so entries
    # are always re-sorted back to this master order at render time.
    education_order = {entry.id: i for i, entry in enumerate(content.education)}
    experience_order = {entry.id: i for i, entry in enumerate(content.experience)}
    project_order = {project.id: i for i, project in enumerate(content.projects)}

    section_titles = {
        "education": "Education",
        "skills": "Languages and Technologies",
        "experience": "Experience",
        "projects": "Projects",
    }

    sections: list[dict] = []
    for key in selection.section_order:
        if key == "education":
            entries: list[EducationEntry] = []
            ordered_education = sorted(
                selection.education,
                key=lambda edu_sel: education_order.get(edu_sel.entry_id, len(education_order)),
            )
            for edu_sel in ordered_education:
                entry = education_by_id[edu_sel.entry_id]
                entries.append(
                    EducationEntry(
                        **entry.model_dump(exclude={"bullets"}),
                        bullets=_resolve_bullets(entry.bullets, edu_sel.bullet_ids),
                    )
                )
            sections.append({"key": key, "title": section_titles[key], "entries": entries})
        elif key == "skills":
            lines: list[SkillLine] = [
                skills_by_id[line_id]
                for line_id in selection.skill_line_ids
                if line_id in skills_by_id
            ]
            sections.append({"key": key, "title": section_titles[key], "lines": lines})
        elif key == "experience":
            entries = []
            ordered_experience = sorted(
                selection.experience,
                key=lambda exp_sel: experience_order.get(exp_sel.entry_id, len(experience_order)),
            )
            for exp_sel in ordered_experience:
                entry = experience_by_id[exp_sel.entry_id]
                entries.append(
                    ExperienceEntry(
                        **entry.model_dump(exclude={"bullets"}),
                        bullets=_resolve_bullets(entry.bullets, exp_sel.bullet_ids),
                    )
                )
            sections.append({"key": key, "title": section_titles[key], "entries": entries})
        elif key == "projects":
            ordered_project_ids = sorted(
                (pid for pid in selection.project_ids if pid in projects_by_id),
                key=lambda pid: project_order.get(pid, len(project_order)),
            )
            projects: list[ProjectEntry] = [
                projects_by_id[project_id] for project_id in ordered_project_ids
            ]
            sections.append({"key": key, "title": section_titles[key], "projects": projects})

    with PREAMBLE_PATH.open(encoding="utf-8") as handle:
        preamble = handle.read()

    return {
        "preamble": preamble,
        "header": content.header.model_dump(),
        "sections": sections,
    }


def render_tex(content: ResumeContent, selection: Selection) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(default=False),
        block_start_string="<%",
        block_end_string="%>",
        variable_start_string="<<",
        variable_end_string=">>",
        comment_start_string="<#",
        comment_end_string="#>",
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("resume.tex.jinja")
    context = build_render_context(content, selection)
    return template.render(**context)


def write_tex(tex_path: Path, content: ResumeContent, selection: Selection) -> Path:
    tex_path.parent.mkdir(parents=True, exist_ok=True)
    tex_path.write_text(render_tex(content, selection), encoding="utf-8")
    return tex_path


def compile_pdf(tex_path: Path, output_dir: Path | None = None) -> Path:
    tex_path = tex_path.resolve()
    work_dir = (output_dir or tex_path.parent).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)

    tectonic = _find_tectonic()
    try:
        result = subprocess.run(
            [tectonic, "--outdir", str(work_dir), str(tex_path)],
            capture_output=True,
            text=True,
            cwd=str(tex_path.parent),
            check=False,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        # Without a timeout, a hung Tectonic process (e.g. a font fetch
        # stalling) blocks the CLI forever, since fit_to_one_page() calls
        # this in a loop with no other way to notice a stuck compile.
        raise RuntimeError(
            f"Tectonic timed out compiling {tex_path} after {exc.timeout}s."
        ) from exc
    if result.returncode != 0:
        raise RuntimeError(
            f"Tectonic failed for {tex_path}:\n{result.stdout}\n{result.stderr}"
        )

    pdf_path = work_dir / f"{tex_path.stem}.pdf"
    if not pdf_path.exists():
        raise FileNotFoundError(f"Expected PDF not found at {pdf_path}")
    return pdf_path


def count_pages(pdf_path: Path) -> int:
    reader = PdfReader(str(pdf_path))
    return len(reader.pages)


def extract_text(pdf_path: Path) -> str:
    reader = PdfReader(str(pdf_path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def render_and_compile(
    content: ResumeContent,
    selection: Selection,
    tex_path: Path,
    pdf_dir: Path | None = None,
) -> tuple[Path, Path, int]:
    write_tex(tex_path, content, selection)
    pdf_path = compile_pdf(tex_path, pdf_dir)
    return tex_path, pdf_path, count_pages(pdf_path)


def get_droppable_items(
    content: ResumeContent,
    selection: Selection,
) -> list[tuple[str, int, str]]:
    """Return droppable item IDs sorted by ascending priority (lowest first)."""
    pinned = _pinned_map(content)
    priorities = _priority_map(selection, content)
    droppable: list[tuple[str, int, str]] = []

    for edu_sel in selection.education:
        if len(edu_sel.bullet_ids) <= 1:
            continue
        for bullet_id in edu_sel.bullet_ids:
            if pinned.get(bullet_id, False):
                continue
            droppable.append((bullet_id, priorities.get(bullet_id, 50), "education"))

    for exp_sel in selection.experience:
        if len(exp_sel.bullet_ids) <= 1:
            continue
        for bullet_id in exp_sel.bullet_ids:
            if pinned.get(bullet_id, False):
                continue
            droppable.append((bullet_id, priorities.get(bullet_id, 50), "experience"))

    if len(selection.skill_line_ids) > 1:
        for line_id in selection.skill_line_ids:
            if pinned.get(line_id, False):
                continue
            droppable.append((line_id, priorities.get(line_id, 50), "skills"))

    for project_id in selection.project_ids:
        if pinned.get(project_id, False):
            continue
        droppable.append((project_id, priorities.get(project_id, 50), "projects"))

    droppable.sort(key=lambda item: item[1])
    return droppable


def get_fillable_items(
    content: ResumeContent,
    selection: Selection,
) -> list[tuple[str, int, str]]:
    """Return currently-unselected item IDs sorted by descending priority (most relevant first)."""
    priorities = _priority_map(selection, content)
    experience_by_id = {entry.id: entry for entry in content.experience}
    education_by_id = {entry.id: entry for entry in content.education}
    fillable: list[tuple[str, int, str]] = []

    for edu_sel in selection.education:
        entry = education_by_id.get(edu_sel.entry_id)
        if entry is None:
            continue
        for bullet in entry.bullets:
            if bullet.id not in edu_sel.bullet_ids:
                fillable.append((bullet.id, priorities.get(bullet.id, 50), "education"))

    for exp_sel in selection.experience:
        entry = experience_by_id.get(exp_sel.entry_id)
        if entry is None:
            continue
        for bullet in entry.bullets:
            if bullet.id not in exp_sel.bullet_ids:
                fillable.append((bullet.id, priorities.get(bullet.id, 50), "experience"))

    for line in content.skills:
        if line.id not in selection.skill_line_ids:
            fillable.append((line.id, priorities.get(line.id, 50), "skills"))

    for project in content.projects:
        if project.id not in selection.project_ids:
            fillable.append((project.id, priorities.get(project.id, 50), "projects"))

    fillable.sort(key=lambda item: item[1], reverse=True)
    return fillable


def drop_item(selection: Selection, item_id: str, item_type: str) -> bool:
    if item_type == "education":
        for edu_sel in selection.education:
            if item_id in edu_sel.bullet_ids and len(edu_sel.bullet_ids) > 1:
                edu_sel.bullet_ids = [
                    bullet_id for bullet_id in edu_sel.bullet_ids if bullet_id != item_id
                ]
                return True
        return False

    if item_type == "experience":
        for exp_sel in selection.experience:
            if item_id in exp_sel.bullet_ids and len(exp_sel.bullet_ids) > 1:
                exp_sel.bullet_ids = [
                    bullet_id for bullet_id in exp_sel.bullet_ids if bullet_id != item_id
                ]
                return True
        return False

    if item_type == "skills":
        if item_id in selection.skill_line_ids and len(selection.skill_line_ids) > 1:
            selection.skill_line_ids = [
                line_id for line_id in selection.skill_line_ids if line_id != item_id
            ]
            return True
        return False

    if item_type == "projects":
        if item_id in selection.project_ids:
            selection.project_ids = [
                project_id
                for project_id in selection.project_ids
                if project_id != item_id
            ]
            return True
        return False

    return False
