from __future__ import annotations

import json
from pathlib import Path

import click

from .render import extract_text, load_content, master_selection, render_and_compile
from .select import load_selection
from .service import slugify as _slugify
from .service import tailor_lead

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT_ROOT / "out"
JOBS_DIR = PROJECT_ROOT / "jobs"


@click.group()
def cli() -> None:
    """Tailored resume pipeline for Curtis Welter."""


@cli.command("master")
@click.option(
    "--output",
    "output_dir",
    type=click.Path(path_type=Path),
    default=OUT_DIR,
    show_default=True,
    help="Directory for master.tex and master.pdf",
)
def master_cmd(output_dir: Path) -> None:
    """Render the full master resume with all content."""
    content = load_content()
    selection = master_selection(content)
    output_dir.mkdir(parents=True, exist_ok=True)
    tex_path = output_dir / "master.tex"
    tex_path, pdf_path, pages = render_and_compile(
        content, selection, tex_path, output_dir
    )
    click.echo(f"Wrote {tex_path}")
    click.echo(f"Wrote {pdf_path} ({pages} page(s))")


@cli.command("render")
@click.argument("selection_path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Directory for curtis_welter_resume.tex and curtis_welter_resume.pdf",
)
def render_cmd(selection_path: Path, output_dir: Path | None) -> None:
    """Render a resume from an existing selection.json without calling Claude."""
    content = load_content()
    selection = load_selection(selection_path)
    output_dir = output_dir or selection_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    tex_path = output_dir / "curtis_welter_resume.tex"
    tex_path, pdf_path, pages = render_and_compile(
        content, selection, tex_path, output_dir
    )
    click.echo(f"Wrote {tex_path}")
    click.echo(f"Wrote {pdf_path} ({pages} page(s))")


@cli.command("tailor")
@click.argument("job_file", type=click.Path(exists=True, path_type=Path))
@click.option("--slug", default=None, help="Job folder name under jobs/")
@click.option(
    "--from-selection",
    is_flag=True,
    help="Skip Claude and use existing selection.json in the job folder",
)
@click.option("--model", default=None, help="Claude model override")
@click.option("--no-fill", is_flag=True, help="Disable fill pass after trimming")
def tailor_cmd(
    job_file: Path,
    slug: str | None,
    from_selection: bool,
    model: str | None,
    no_fill: bool,
) -> None:
    """Tailor a one-page resume for a job description file."""
    content = load_content()
    job_text = job_file.read_text(encoding="utf-8")
    job_slug = slug or _slugify(job_file.stem)

    if from_selection:
        selection_path = JOBS_DIR / job_slug / "selection.json"
        if not selection_path.exists():
            raise click.ClickException(
                f"No selection found at {selection_path}. Run tailor without --from-selection first."
            )
    else:
        click.echo("Selecting content with Claude...")

    try:
        result = tailor_lead(
            job_text,
            job_slug,
            content=content,
            from_selection=from_selection,
            model=model,
            fill=not no_fill,
            jobs_dir=JOBS_DIR,
        )
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc

    if from_selection:
        click.echo(f"Loaded existing selection from {result.selection_path}")
    else:
        click.echo(f"Wrote {result.selection_path}")
        click.echo(f"Rationale: {result.selection.rationale}")

    click.echo("Fitting to one page...")
    if result.dropped_items:
        click.echo(
            "Dropped items to fit one page: " + ", ".join(result.dropped_items)
        )
    if result.fill_attempts:
        click.echo(f"Fill pass restored {result.fill_attempts} item(s).")

    click.echo(f"Wrote {result.tex_path}")
    click.echo(f"Wrote {result.pdf_path} ({result.pages} page(s))")
    if result.pages > 1:
        click.echo(
            "Warning: resume is still longer than one page after trimming.",
            err=True,
        )


@cli.command("inventory")
def inventory_cmd() -> None:
    """Print a JSON inventory of all content IDs for debugging."""
    content = load_content()
    payload = {
        "education": [
            {
                "id": entry.id,
                "bullets": [bullet.id for bullet in entry.bullets],
                "tags": entry.tags,
            }
            for entry in content.education
        ],
        "skills": [{"id": line.id, "tags": line.tags} for line in content.skills],
        "experience": [
            {
                "id": entry.id,
                "bullets": [bullet.id for bullet in entry.bullets],
                "tags": entry.tags,
            }
            for entry in content.experience
        ],
        "projects": [{"id": project.id, "tags": project.tags} for project in content.projects],
    }
    click.echo(json.dumps(payload, indent=2))


@cli.command("verify-ats")
@click.argument("pdf_path", type=click.Path(exists=True, path_type=Path))
def verify_ats_cmd(pdf_path: Path) -> None:
    """Extract text from a PDF to verify ATS parsability."""
    text = extract_text(pdf_path)
    click.echo(text[:2000])
    click.echo("\n---")
    click.echo(f"Contains name: {'Curtis Welter' in text}")
    click.echo(f"Contains CDC: {'Centers for Disease Control' in text or 'CDC' in text}")


if __name__ == "__main__":
    cli()
