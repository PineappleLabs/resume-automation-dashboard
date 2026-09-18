from __future__ import annotations

import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Depends
from fastapi.responses import RedirectResponse

from ..security import require_login

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_login)])


@router.post("/gmail/refresh")
def refresh_gmail() -> RedirectResponse:
    # Imported lazily, not at module load time: ingest_gmail.config requires
    # ANTHROPIC_API_KEY eagerly at import, and a module-level import here would make the
    # whole dashboard fail to start whenever that's unset, just to support one optional
    # button (same lesson as services/api/app/config.py dropping DATABASE_URL/
    # ANTHROPIC_API_KEY from its own required settings after the Alembic-startup bug).
    from ingest_gmail.sync import run_once

    try:
        stats = run_once()
    except Exception as exc:  # noqa: BLE001 -- surfaced to the user via redirect, logged here
        logger.exception("Gmail refresh failed")
        params = {"gmail_error": str(exc)}
    else:
        params = {
            "gmail_total": stats.total,
            "gmail_created": stats.leads_created,
            "gmail_events": stats.interview_events_created,
            "gmail_filtered": stats.filtered_by_location,
        }
    return RedirectResponse(url=f"/leads?{urlencode(params)}", status_code=303)
