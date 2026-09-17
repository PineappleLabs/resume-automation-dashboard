from __future__ import annotations

from pathlib import Path

from resume_pipeline import fit as fit_module
from resume_pipeline.fit import fit_to_one_page
from resume_pipeline.render import master_selection
from resume_pipeline.schema import Selection


def _count_selected(selection: Selection) -> int:
    total = sum(len(entry.bullet_ids) for entry in selection.education)
    total += sum(len(entry.bullet_ids) for entry in selection.experience)
    total += len(selection.skill_line_ids)
    total += len(selection.project_ids)
    return total


def _fake_compile_factory(threshold: int):
    """Simulate render_and_compile: pages=2 while more than `threshold` items
    are selected, else 1. Avoids requiring a real Tectonic install in tests.
    """

    def _fake(content, selection, tex_path, pdf_dir=None):
        pages = 2 if _count_selected(selection) > threshold else 1
        return tex_path, Path(tex_path).with_suffix(".pdf"), pages

    return _fake


def test_fit_to_one_page_never_drops_pinned_bullet(monkeypatch, sample_content, tmp_path):
    selection = master_selection(sample_content)
    starting_count = _count_selected(selection)
    monkeypatch.setattr(
        fit_module, "render_and_compile", _fake_compile_factory(threshold=starting_count - 4)
    )

    result = fit_to_one_page(
        selection,
        tex_path=tmp_path / "resume.tex",
        pdf_dir=tmp_path,
        content=sample_content,
        max_pages=1,
    )

    assert result.pages == 1
    assert "exp-1-b1" not in result.dropped_items  # pinned bullet must survive
    exp_1_selection = next(e for e in result.selection.experience if e.entry_id == "exp-1")
    assert "exp-1-b1" in exp_1_selection.bullet_ids


def test_fit_to_one_page_drops_lowest_priority_first(monkeypatch, sample_content, tmp_path):
    selection = master_selection(sample_content)
    starting_count = _count_selected(selection)
    monkeypatch.setattr(
        fit_module, "render_and_compile", _fake_compile_factory(threshold=starting_count - 1)
    )

    result = fit_to_one_page(
        selection,
        tex_path=tmp_path / "resume.tex",
        pdf_dir=tmp_path,
        content=sample_content,
        max_pages=1,
        fill=False,
    )

    # Only one item needs to go; it should be the single lowest-priority
    # droppable bullet (exp-2-b2, priority 10).
    assert result.dropped_items == ["exp-2-b2"]
    assert result.pages == 1


def test_fit_to_one_page_already_fits(monkeypatch, sample_content, tmp_path):
    selection = master_selection(sample_content)
    monkeypatch.setattr(fit_module, "render_and_compile", _fake_compile_factory(threshold=999))

    result = fit_to_one_page(
        selection,
        tex_path=tmp_path / "resume.tex",
        pdf_dir=tmp_path,
        content=sample_content,
        max_pages=1,
    )

    assert result.pages == 1
    assert result.dropped_items == []
    assert result.fill_attempts == 0
