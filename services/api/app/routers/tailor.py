from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from resume_pipeline.service import tailor_lead

from ..config import settings
from ..db import get_db
from ..models import Lead
from ..security import require_login
from ..templating import templates

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_login)])


def _job_dir(slug: str) -> Path:
    return settings.pipeline_jobs_dir / slug


def existing_tailor_result(lead: Lead) -> dict[str, Any] | None:
    """Read the last tailor run for this lead off disk, if one exists."""
    if not lead.resume_job_slug:
        return None
    job_dir = _job_dir(lead.resume_job_slug)
    selection_path = job_dir / "selection.json"
    pdf_path = job_dir / "curtis_welter_resume.pdf"
    if not selection_path.exists() or not pdf_path.exists():
        return None
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    return {
        "rationale": selection.get("rationale", ""),
        "pdf_available": True,
    }


@router.post("/leads/{lead_id}/tailor")
def tailor_lead_route(lead_id: int, request: Request, db: Session = Depends(get_db)) -> object:
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    if not lead.jd_text or not lead.jd_text.strip():
        return templates.TemplateResponse(
            request,
            "leads/_tailor_error.html",
            {"message": "This lead has no job description text to tailor against."},
        )

    try:
        result = tailor_lead(
            lead.jd_text,
            lead.resume_job_slug,
            jobs_dir=settings.pipeline_jobs_dir,
        )
    except Exception as exc:  # noqa: BLE001 -- surfaced to the user, logged for diagnosis
        logger.exception("Tailoring failed for lead %s", lead_id)
        return templates.TemplateResponse(
            request,
            "leads/_tailor_error.html",
            {"message": str(exc)},
        )

    return templates.TemplateResponse(
        request,
        "leads/_tailor_result.html",
        {
            "lead": lead,
            "rationale": result.selection.rationale,
            "pages": result.pages,
            "dropped_items": result.dropped_items,
        },
    )


@router.get("/leads/{lead_id}/resume.pdf")
def download_resume(lead_id: int, db: Session = Depends(get_db)) -> FileResponse:
    lead = db.get(Lead, lead_id)
    if lead is None or not lead.resume_job_slug:
        raise HTTPException(status_code=404, detail="No resume for this lead yet")
    pdf_path = _job_dir(lead.resume_job_slug) / "curtis_welter_resume.pdf"
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="No resume for this lead yet")
    filename = f"{lead.resume_job_slug}-resume.pdf"
    return FileResponse(pdf_path, media_type="application/pdf", filename=filename)
