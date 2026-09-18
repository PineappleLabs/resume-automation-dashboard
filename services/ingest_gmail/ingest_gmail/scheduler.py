from __future__ import annotations

from apscheduler.schedulers.blocking import BlockingScheduler

from .config import settings
from .sync import run_once


def start_polling() -> None:
    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(run_once, "interval", minutes=settings.poll_interval_minutes)
    scheduler.start()
