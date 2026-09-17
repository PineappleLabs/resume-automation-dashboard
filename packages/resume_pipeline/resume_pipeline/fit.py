from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path

from .render import (
    drop_item,
    get_droppable_items,
    get_fillable_items,
    load_content,
    render_and_compile,
)
from .schema import ResumeContent, Selection


@dataclass
class FitResult:
    selection: Selection
    tex_path: Path
    pdf_path: Path
    pages: int
    dropped_items: list[str]
    fill_attempts: int


def fit_to_one_page(
    selection: Selection,
    tex_path: Path,
    pdf_dir: Path | None = None,
    content: ResumeContent | None = None,
    max_pages: int = 1,
    fill: bool = True,
) -> FitResult:
    content = content or load_content()
    working = copy.deepcopy(selection)
    dropped: list[str] = []
    fill_attempts = 0

    tex_path, pdf_path, pages = render_and_compile(
        content, working, tex_path, pdf_dir
    )

    while pages > max_pages:
        droppable = get_droppable_items(content, working)
        if not droppable:
            break
        item_id, _priority, item_type = droppable[0]
        if not drop_item(working, item_id, item_type):
            break
        dropped.append(item_id)
        tex_path, pdf_path, pages = render_and_compile(
            content, working, tex_path, pdf_dir
        )

    if fill and pages <= max_pages:
        fill_attempts = _fill_remaining_space(
            content, working, tex_path, pdf_dir, max_pages
        )
        # Always re-render here, even when every fill attempt failed.
        # _fill_remaining_space's own render_and_compile calls leave the
        # .tex/.pdf on disk reflecting whichever item it last tried adding,
        # which may not match `working` if that last attempt was reverted.
        # Without this, a failed-then-reverted add can leave a stale,
        # over-length PDF on disk while this function reports the correct
        # one-page state.
        _, pdf_path, pages = render_and_compile(
            content, working, tex_path, pdf_dir
        )

    return FitResult(
        selection=working,
        tex_path=tex_path,
        pdf_path=pdf_path,
        pages=pages,
        dropped_items=dropped,
        fill_attempts=fill_attempts,
    )


def _fill_remaining_space(
    content: ResumeContent,
    selection: Selection,
    tex_path: Path,
    pdf_dir: Path | None,
    max_pages: int,
) -> int:
    """Greedily add the highest-priority unselected content that still fits.

    Repeatedly re-ranks all currently-unselected bullets/skills/projects by
    priority and adds the best one that keeps the resume within max_pages,
    so the page is always filled with the most relevant leftover content
    rather than being left with unused whitespace.
    """
    attempts = 0
    while True:
        candidates = get_fillable_items(content, selection)
        if not candidates:
            break

        added = False
        for item_id, _priority, _item_type in candidates:
            if not _restore_item(selection, item_id, content):
                continue
            _, _, pages = render_and_compile(content, selection, tex_path, pdf_dir)
            if pages <= max_pages:
                attempts += 1
                added = True
                break
            _drop_restored_item(selection, item_id, content)

        if not added:
            break
    return attempts


def _restore_item(
    selection: Selection, item_id: str, content: ResumeContent
) -> bool:
    for entry in content.education:
        bullet_ids = [bullet.id for bullet in entry.bullets]
        if item_id not in bullet_ids:
            continue
        for edu_sel in selection.education:
            if edu_sel.entry_id == entry.id and item_id not in edu_sel.bullet_ids:
                edu_sel.bullet_ids.append(item_id)
                return True
        return False

    for entry in content.experience:
        bullet_ids = [bullet.id for bullet in entry.bullets]
        if item_id not in bullet_ids:
            continue
        for exp_sel in selection.experience:
            if exp_sel.entry_id == entry.id and item_id not in exp_sel.bullet_ids:
                exp_sel.bullet_ids.append(item_id)
                return True
        return False

    skill_ids = [line.id for line in content.skills]
    if item_id in skill_ids and item_id not in selection.skill_line_ids:
        selection.skill_line_ids.append(item_id)
        return True

    project_ids = [project.id for project in content.projects]
    if item_id in project_ids and item_id not in selection.project_ids:
        selection.project_ids.append(item_id)
        return True

    return False


def _drop_restored_item(
    selection: Selection, item_id: str, content: ResumeContent
) -> None:
    for entry in content.education:
        if item_id in [bullet.id for bullet in entry.bullets]:
            drop_item(selection, item_id, "education")
            return
    for entry in content.experience:
        if item_id in [bullet.id for bullet in entry.bullets]:
            drop_item(selection, item_id, "experience")
            return
    if item_id in [line.id for line in content.skills]:
        drop_item(selection, item_id, "skills")
        return
    if item_id in [project.id for project in content.projects]:
        drop_item(selection, item_id, "projects")
