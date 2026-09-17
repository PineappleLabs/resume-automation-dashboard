# Tailored Resume Pipeline

Generate a one-page, job-specific resume from a structured master content file.

## Setup

1. Install [Tectonic](https://tectonic-typesetting.github.io/) 0.17+ (required for `fontawesome5`).
2. Install this package (from `packages/resume_pipeline/`):

```bash
pip install -e ".[dev]"
```

3. Copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY`.

Ensure Tectonic is on PATH, or install to `%LOCALAPPDATA%\tectonic\tectonic.exe` (the default used by this project).

This package has no dependency on the dashboard/database services under `services/` at the monorepo root — the commands below work standalone, exactly as they always have.

## Project layout

- `content/content.yaml` — source of truth for all resume content
- `templates/preamble.tex` — LaTeX styling copied from `main.tex`
- `templates/resume.tex.jinja` — body template
- `out/` — generated master resume
- `jobs/<slug>/` — per-job outputs (`job.txt`, `selection.json`, `curtis_welter_resume.tex`, `curtis_welter_resume.pdf`)
- `main.tex` — original one-page resume kept as visual reference

## Commands

Render the full master resume (all content):

```bash
python -m resume_pipeline.cli master
```

Tailor a resume for a job description file:

```bash
python -m resume_pipeline.cli tailor path/to/job.txt --slug company-role
```

Re-render from an existing selection without calling Claude:

```bash
python -m resume_pipeline.cli tailor jobs/company-role/job.txt --from-selection
```

Render any saved selection:

```bash
python -m resume_pipeline.cli render jobs/company-role/selection.json
```

Verify ATS text extraction:

```bash
python -m resume_pipeline.cli verify-ats out/master.pdf
```

## Workflow

1. Add or update entries in `content/content.yaml`.
2. Export your LinkedIn profile as PDF and review extracted text:

```bash
python -m resume_pipeline.import_linkedin Profile.pdf --merge
python -m resume_pipeline.import_linkedin Profile.pdf --check
```

3. Review `content/content.yaml` for anything the merge missed.
4. Paste a job description into a text file.
5. Run `python -m resume_pipeline.cli tailor jobs/my-job/job.txt`.
6. Review `jobs/my-job/selection.json` and edit IDs/priorities if needed.
7. Re-render with `--from-selection` until satisfied.

## Content rules

- Every bullet has a stable `id`, `tags`, and `priority`.
- Set `pinned: true` on bullets that must never be dropped during one-page fitting.
- Bullet `text` fields contain LaTeX source (e.g. `C\\#`, `\\textbf{Coursework:}`).
- The Claude step only selects existing IDs — it never rewrites bullet text.

## One-page fitting

`fit.py` renders the selected content, counts pages, and drops the lowest-priority unpinned bullet until the resume fits one page. Each experience/education entry keeps at least one bullet.

## Library use

`resume_pipeline.service.tailor_lead()` is the same select → fit → render pipeline behind the `tailor` command, exposed as a plain function so other code (the dashboard API, the auto-apply agent) can call it directly instead of shelling out to the CLI.

## Testing

```bash
pytest
```

Tests stub the Anthropic client and the Tectonic-invoking `render_and_compile` step, so they run without network access or Tectonic installed.
