from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import LEAD_STATUSES, INTERVIEW_TYPES, InterviewEvent, Lead, StatusHistory
from ..security import require_login
from ..slugs import unique_lead_slug
from ..templating import templates
from .tailor import existing_tailor_result

router = APIRouter(dependencies=[Depends(require_login)])


@router.get("/leads")
def list_leads(request: Request, db: Session = Depends(get_db)) -> object:
    next_event_sq = (
        select(
            InterviewEvent.lead_id.label("lead_id"),
            func.min(InterviewEvent.scheduled_at).label("next_at"),
        )
        .where(InterviewEvent.scheduled_at >= func.now())
        .group_by(InterviewEvent.lead_id)
        .subquery()
    )
    stmt = (
        select(Lead, next_event_sq.c.next_at)
        .outerjoin(next_event_sq, Lead.id == next_event_sq.c.lead_id)
        .order_by(next_event_sq.c.next_at.asc().nulls_last(), Lead.created_at.desc())
    )
    rows = db.execute(stmt).all()
    leads = [{"lead": lead, "next_event_at": next_at} for lead, next_at in rows]

    gmail_refresh = None
    params = request.query_params
    if "gmail_error" in params:
        gmail_refresh = {"error": params["gmail_error"]}
    elif "gmail_total" in params:
        gmail_refresh = {
            "total": params.get("gmail_total"),
            "created": params.get("gmail_created"),
            "events": params.get("gmail_events"),
            "filtered": params.get("gmail_filtered"),
        }

    return templates.TemplateResponse(
        request, "leads/list.html", {"leads": leads, "gmail_refresh": gmail_refresh}
    )


@router.get("/leads/new")
def new_lead_form(request: Request) -> object:
    return templates.TemplateResponse(request, "leads/new.html", {})


@router.post("/leads")
def create_lead(
    request: Request,
    company: str = Form(...),
    role_title: str = Form(...),
    jd_text: str = Form(...),
    jd_url: str = Form(""),
    recruiter_name: str = Form(""),
    recruiter_contact: str = Form(""),
    db: Session = Depends(get_db),
) -> object:
    lead = Lead(
        company=company.strip(),
        role_title=role_title.strip(),
        source="manual",
        jd_text=jd_text.strip(),
        jd_url=jd_url.strip() or None,
        recruiter_name=recruiter_name.strip() or None,
        recruiter_contact=recruiter_contact.strip() or None,
        status="new",
    )
    db.add(lead)
    db.flush()
    lead.resume_job_slug = unique_lead_slug(db, lead.company, lead.role_title)
    db.add(StatusHistory(lead_id=lead.id, old_status=None, new_status="new", changed_by="user"))
    db.commit()
    db.refresh(lead)
    return RedirectResponse(url=f"/leads/{lead.id}", status_code=303)


@router.get("/leads/{lead_id}")
def lead_detail(lead_id: int, request: Request, db: Session = Depends(get_db)) -> object:
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return templates.TemplateResponse(
        request,
        "leads/detail.html",
        {
            "lead": lead,
            "lead_statuses": LEAD_STATUSES,
            "interview_types": INTERVIEW_TYPES,
            "tailor_result": existing_tailor_result(lead),
        },
    )


@router.post("/leads/{lead_id}/status")
def update_status(
    lead_id: int,
    request: Request,
    new_status: str = Form(...),
    reason: str = Form(""),
    db: Session = Depends(get_db),
) -> object:
    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    if new_status not in LEAD_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")

    old_status = lead.status
    lead.status = new_status
    db.add(
        StatusHistory(
            lead_id=lead.id,
            old_status=old_status,
            new_status=new_status,
            changed_by="user",
            reason=reason or None,
        )
    )
    db.commit()
    db.refresh(lead)

    return templates.TemplateResponse(
        request,
        "leads/_status_panel.html",
        {"lead": lead, "lead_statuses": LEAD_STATUSES},
    )
