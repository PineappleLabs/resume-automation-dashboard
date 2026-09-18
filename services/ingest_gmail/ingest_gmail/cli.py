from __future__ import annotations

import click

from .gmail_auth import authorize
from .scheduler import start_polling
from .sync import run_once


@click.group()
def cli() -> None:
    """Gmail inbox ingestion for the job-search platform."""


@cli.command("authorize")
def authorize_cmd() -> None:
    """One-time interactive OAuth consent. Opens your browser."""
    authorize()
    click.echo("Credentials saved.")


@cli.command("run-once")
def run_once_cmd() -> None:
    """Run a single sync pass against Gmail and exit."""
    stats = run_once()
    click.echo(
        f"{stats.total} message(s): {stats.leads_created} lead(s) created, "
        f"{stats.filtered_by_location} filtered out by location, "
        f"{stats.classified} classified, {stats.prefiltered} skipped by prefilter, "
        f"{stats.skipped_existing} already seen."
    )


@cli.command("poll")
def poll_cmd() -> None:
    """Run continuously, polling Gmail on an interval."""
    start_polling()


if __name__ == "__main__":
    cli()
