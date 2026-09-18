from __future__ import annotations

from jobsearch_db.models import Lead
from resume_pipeline.service import slugify
from sqlalchemy import select
from sqlalchemy.orm import Session


def unique_lead_slug(db: Session, company: str, role_title: str) -> str:
    """Generate a resume_job_slug that doesn't collide with an existing lead's.

    Mirrors services/api/app/slugs.py exactly -- duplicated rather than shared because
    that module lives inside the FastAPI app package, not a reusable library.
    """
    base = slugify(f"{company}-{role_title}")
    candidate = base
    suffix = 2
    while db.scalar(select(Lead.id).where(Lead.resume_job_slug == candidate)) is not None:
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate
