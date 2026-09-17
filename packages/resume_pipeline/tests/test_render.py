from __future__ import annotations

from resume_pipeline.render import build_render_context, master_selection, render_tex


def test_build_render_context_includes_selected_sections(sample_content):
    selection = master_selection(sample_content)
    context = build_render_context(sample_content, selection)

    assert context["header"]["name"] == "Test Person"
    section_keys = [section["key"] for section in context["sections"]]
    assert section_keys == ["education", "skills", "experience", "projects"]

    experience_section = next(s for s in context["sections"] if s["key"] == "experience")
    entry_ids = [entry.id for entry in experience_section["entries"]]
    assert entry_ids == ["exp-1", "exp-2"]


def test_render_tex_renders_selected_bullets_only(sample_content):
    selection = master_selection(sample_content)
    # Drop one experience bullet from the selection to confirm rendering
    # reflects the selection, not the full content.
    selection.experience[0].bullet_ids = ["exp-1-b1"]

    tex = render_tex(sample_content, selection)

    assert "Pinned achievement bullet." in tex
    assert "Lower priority bullet." not in tex
    assert "Acme Corp" in tex
    assert "\\begin{document}" in tex
    assert "\\end{document}" in tex
