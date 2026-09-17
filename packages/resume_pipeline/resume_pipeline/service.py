from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .fit import fit_to_one_page
from .render import load_content
from .schema import ResumeContent, Selection
from .select import load_selection, save_selection, select_for_job

PROJECT_ROOT = Path(__file__).resolve().parent.parent
JOBS_DIR = PROJECT_ROOT / "jobs"


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "job"


@dataclass
class TailorResult:
    slug: str
    job_dir: Path
    job_path: Path
    selection: Selection
    selection_path: Path
    tex_path: Path
    pdf_path: Path
    pages: int
    dropped_items: list[str]
    fill_attempts: int
    from_selection: bool


def tailor_lead(
    job_description: str,
    slug: str,
    content: ResumeContent | None = None,
    from_selection: bool = False,
    model: str | None = None,
    fill: bool = True,
    jobs_dir: Path | None = None,
) -> TailorResult:
    """Select, fit, and render a one-page resume for a job description.

    This is the single entry point behind the `tailor` CLI command, and the
    one the dashboard API and auto-apply agent call too, so all three
    surfaces run the exact same pipeline against the same content.yaml.
    """
    content = content or load_content()
    job_dir = (jobs_dir or JOBS_DIR) / slug
    job_dir.mkdir(parents=True, exist_ok=True)

    job_path = job_dir / "job.txt"
    job_path.write_text(job_description, encoding="utf-8")

    selection_path = job_dir / "selection.json"
    if from_selection:
        if not selection_path.exists():
            raise FileNotFoundError(
                f"No selection found at {selection_path}. "
                "Run tailor_lead with from_selection=False first."
            )
        selection = load_selection(selection_path)
    else:
        selection = select_for_job(job_description, content=content, model=model)
        save_selection(selection, selection_path)

    fit_result = fit_to_one_page(
        selection,
        tex_path=job_dir / "curtis_welter_resume.tex",
        pdf_dir=job_dir,
        content=content,
        fill=fill,
    )
    save_selection(fit_result.selection, selection_path)

    return TailorResult(
        slug=slug,
        job_dir=job_dir,
        job_path=job_path,
        selection=fit_result.selection,
        selection_path=selection_path,
        tex_path=fit_result.tex_path,
        pdf_path=fit_result.pdf_path,
        pages=fit_result.pages,
        dropped_items=fit_result.dropped_items,
        fill_attempts=fit_result.fill_attempts,
        from_selection=from_selection,
    )
