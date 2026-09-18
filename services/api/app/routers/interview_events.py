from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import INTERVIEW_TYPES, InterviewEvent, Lead
from ..security import require_login
from ..templating import templates

router = APIRouter(dependencies=[Depends(require_login)])


@router.post("/leads/{lead_id}/interview-events")
def add_interview_event(
    lead_id: int,
    request: Request,
    scheduled_at: dt.datetime = Form(...),
    event_type: str = Form(...),
    location_or_link: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
) -> object:
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    if event_type not in INTERVIEW_TYPES:
        raise HTTPException(status_code=400, detail="Invalid event type")

    db.add(
        InterviewEvent(
            lead_id=lead.id,
            scheduled_at=scheduled_at,
            event_type=event_type,
            location_or_link=location_or_link or None,
            notes=notes or None,
            source="manual",
        )
    )
    db.commit()
    db.refresh(lead)

    return templates.TemplateResponse(
        request,
        "leads/_interview_events.html",
        {"lead": lead, "interview_types": INTERVIEW_TYPES},
    )
