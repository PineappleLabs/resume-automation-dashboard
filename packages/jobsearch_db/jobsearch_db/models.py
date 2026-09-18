from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

LEAD_SOURCES = ("manual", "gmail", "linkedin")
LEAD_STATUSES = (
    "new",
    "tailoring",
    "tailored",
    "applied",
    "interviewing",
    "rejected",
    "offer",
    "withdrawn",
    "archived",
)
STATUS_CHANGED_BY = ("system", "user", "agent")
INTERVIEW_TYPES = ("phone_screen", "technical", "onsite", "call", "other")
INTERVIEW_SOURCES = ("manual", "gmail_parsed")
EMAIL_DIRECTIONS = ("inbound", "outbound")
EMAIL_CLASSIFICATIONS = ("job_lead", "not_job_lead", "skipped_prefilter")


def _in_list_sql(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    company: Mapped[str] = mapped_column(String(255), nullable=False)
    role_title: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    source_ref: Mapped[str | None] = mapped_column(String(512))
    jd_text: Mapped[str | None] = mapped_column(Text)
    jd_url: Mapped[str | None] = mapped_column(String(1024))
    recruiter_name: Mapped[str | None] = mapped_column(String(255))
    recruiter_contact: Mapped[str | None] = mapped_column(String(255))
    received_at: Mapped[dt.datetime | None] = mapped_column(server_default=func.now())
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new")
    resume_job_slug: Mapped[str | None] = mapped_column(String(255), unique=True)
    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    status_history: Mapped[list["StatusHistory"]] = relationship(
        back_populates="lead",
        cascade="all, delete-orphan",
        order_by="StatusHistory.changed_at.desc()",
    )
    interview_events: Mapped[list["InterviewEvent"]] = relationship(
        back_populates="lead",
        cascade="all, delete-orphan",
        order_by="InterviewEvent.scheduled_at.asc()",
    )
    email_threads: Mapped[list["EmailThread"]] = relationship(back_populates="lead")

    __table_args__ = (
        CheckConstraint(_in_list_sql("source", LEAD_SOURCES), name="ck_leads_source"),
        CheckConstraint(_in_list_sql("status", LEAD_STATUSES), name="ck_leads_status"),
        Index("ix_leads_status", "status"),
        Index("ix_leads_created_at", "created_at"),
    )


class StatusHistory(Base):
    __tablename__ = "status_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    old_status: Mapped[str | None] = mapped_column(String(20))
    new_status: Mapped[str] = mapped_column(String(20), nullable=False)
    changed_by: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    confidence: Mapped[float | None] = mapped_column()
    reason: Mapped[str | None] = mapped_column(Text)
    changed_at: Mapped[dt.datetime] = mapped_column(server_default=func.now(), nullable=False)

    lead: Mapped["Lead"] = relationship(back_populates="status_history")

    __table_args__ = (
        CheckConstraint(
            _in_list_sql("new_status", LEAD_STATUSES), name="ck_status_history_new_status"
        ),
        CheckConstraint(
            _in_list_sql("changed_by", STATUS_CHANGED_BY), name="ck_status_history_changed_by"
        ),
        Index("ix_status_history_lead_id", "lead_id"),
    )


class InterviewEvent(Base):
    __tablename__ = "interview_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), nullable=False)
    scheduled_at: Mapped[dt.datetime] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column("type", String(20), nullable=False, default="other")
    location_or_link: Mapped[str | None] = mapped_column(String(512))
    notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    lead: Mapped["Lead"] = relationship(back_populates="interview_events")

    __table_args__ = (
        CheckConstraint(_in_list_sql("type", INTERVIEW_TYPES), name="ck_interview_events_type"),
        CheckConstraint(
            _in_list_sql("source", INTERVIEW_SOURCES), name="ck_interview_events_source"
        ),
        Index("ix_interview_events_lead_id_scheduled_at", "lead_id", "scheduled_at"),
    )


class EmailThread(Base):
    __tablename__ = "email_threads"

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id", ondelete="SET NULL"))
    gmail_thread_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    gmail_history_id: Mapped[int | None] = mapped_column(BigInteger)
    last_message_id: Mapped[str | None] = mapped_column(String(64))
    last_synced_at: Mapped[dt.datetime | None] = mapped_column()
    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    lead: Mapped["Lead | None"] = relationship(back_populates="email_threads")
    messages: Mapped[list["EmailMessage"]] = relationship(
        back_populates="thread",
        cascade="all, delete-orphan",
        order_by="EmailMessage.received_at.asc()",
    )

    __table_args__ = (Index("ix_email_threads_lead_id", "lead_id"),)


class EmailMessage(Base):
    __tablename__ = "email_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    thread_id: Mapped[int] = mapped_column(
        ForeignKey("email_threads.id", ondelete="CASCADE"), nullable=False
    )
    gmail_message_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    from_addr: Mapped[str | None] = mapped_column(String(512))
    subject: Mapped[str | None] = mapped_column(String(1024))
    body_text: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[dt.datetime | None] = mapped_column()
    direction: Mapped[str] = mapped_column(String(20), nullable=False, default="inbound")
    classification: Mapped[str | None] = mapped_column(String(20))
    classification_confidence: Mapped[float | None] = mapped_column()
    location: Mapped[str | None] = mapped_column(String(255))
    location_ok: Mapped[bool | None] = mapped_column()
    created_at: Mapped[dt.datetime] = mapped_column(server_default=func.now(), nullable=False)

    thread: Mapped["EmailThread"] = relationship(back_populates="messages")

    __table_args__ = (
        CheckConstraint(
            _in_list_sql("direction", EMAIL_DIRECTIONS), name="ck_email_messages_direction"
        ),
        CheckConstraint(
            "classification IS NULL OR " + _in_list_sql("classification", EMAIL_CLASSIFICATIONS),
            name="ck_email_messages_classification",
        ),
        CheckConstraint(
            "classification_confidence IS NULL OR "
            "(classification_confidence >= 0 AND classification_confidence <= 1)",
            name="ck_email_messages_confidence_range",
        ),
        Index("ix_email_messages_thread_id", "thread_id"),
        Index("ix_email_messages_received_at", "received_at"),
    )
