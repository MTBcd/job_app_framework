"""MVP database schema — single-user tenancy (user_id on every owned row).

Design notes (see docs/architecture/03-bootstrap-pivot.md):
- No organizations/workspaces: job seekers are individuals.
- `events` is the merged send/reply/bounce/learning log, carrying the V0
  learning weights so pattern confidence keeps improving with usage.
- `jobs` is the Postgres-backed queue (polled with FOR UPDATE SKIP LOCKED)
  that replaces Celery/Redis at this scale.
- String(36) UUIDs keep SQLite (tests) and Postgres (prod) identical.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    clerk_user_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320))
    full_name: Mapped[str] = mapped_column(String(255), default="")
    target_roles: Mapped[list] = mapped_column(JSON, default=list)
    tone_default: Mapped[str] = mapped_column(String(20), default="direct")
    signature: Mapped[str] = mapped_column(Text, default="")
    plan: Mapped[str] = mapped_column(String(20), default="free")
    plan_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    weekly_digest: Mapped[bool] = mapped_column(Boolean, default=True)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(64))


class Document(TimestampMixin, Base):
    """User-uploaded documents; V1 uses kind='cv' with extracted text."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="cv")
    filename: Mapped[str] = mapped_column(String(255), default="")
    content_text: Mapped[str] = mapped_column(Text, default="")
    parsed_profile: Mapped[dict] = mapped_column(JSON, default=dict)
    parse_warnings: Mapped[list] = mapped_column(JSON, default=list)


class Company(TimestampMixin, Base):
    __tablename__ = "companies"
    __table_args__ = (
        Index("ix_companies_user_normalized", "user_id", "name_normalized"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    name_normalized: Mapped[str] = mapped_column(String(255), default="")
    domain: Mapped[str] = mapped_column(String(255), default="")
    domain_source: Mapped[str] = mapped_column(String(50), default="")
    status: Mapped[str] = mapped_column(String(20), default="new")
    notes: Mapped[str] = mapped_column(Text, default="")

    contacts: Mapped[list[Contact]] = relationship(back_populates="company")


class Contact(TimestampMixin, Base):
    __tablename__ = "contacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    company_id: Mapped[str | None] = mapped_column(
        ForeignKey("companies.id"), index=True
    )
    first_name: Mapped[str] = mapped_column(String(120), default="")
    last_name: Mapped[str] = mapped_column(String(120), default="")
    full_name: Mapped[str] = mapped_column(String(255), default="")
    title: Mapped[str] = mapped_column(String(255), default="")
    source: Mapped[str] = mapped_column(String(50), default="import")
    name_parse_warning: Mapped[str] = mapped_column(String(50), default="")

    company: Mapped[Company | None] = relationship(back_populates="contacts")
    email_candidates: Mapped[list[EmailCandidate]] = relationship(
        back_populates="contact"
    )


class EmailCandidate(TimestampMixin, Base):
    """Inferred addresses with the V0 confidence + reasoning trace."""

    __tablename__ = "email_candidates"
    __table_args__ = (UniqueConstraint("contact_id", "email"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    contact_id: Mapped[str] = mapped_column(ForeignKey("contacts.id"), index=True)
    email: Mapped[str] = mapped_column(String(320))
    pattern: Mapped[str] = mapped_column(String(30), default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    reasoning: Mapped[list] = mapped_column(JSON, default=list)
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False)

    contact: Mapped[Contact] = relationship(back_populates="email_candidates")


class Application(TimestampMixin, Base):
    """One outreach attempt: company + contact + drafted content + state."""

    __tablename__ = "applications"

    STATUSES = (
        "draft",
        "researching",
        "ready_for_review",
        "approved",
        "sent",
        "replied",
        "positive_reply",
        "interview",
        "rejected",
        "no_response",
        "bounced",
        "failed",
        "suppressed",
        "archived",
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    contact_id: Mapped[str | None] = mapped_column(ForeignKey("contacts.id"))
    opportunity_id: Mapped[str | None] = mapped_column(ForeignKey("opportunities.id"))
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    pipeline_stage: Mapped[str] = mapped_column(String(30), default="")
    tone: Mapped[str] = mapped_column(String(20), default="direct")
    optimized_cv: Mapped[str | None] = mapped_column(Text)
    contact_rationale: Mapped[str] = mapped_column(Text, default="")
    personalization_plan: Mapped[dict] = mapped_column(JSON, default=dict)
    email_source: Mapped[str] = mapped_column(String(30), default="")
    email_pattern: Mapped[str] = mapped_column(String(30), default="")
    email_label: Mapped[str] = mapped_column(String(40), default="")
    email_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    approved_subject: Mapped[str | None] = mapped_column(String(500))
    approved_body: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reply_preview: Mapped[str] = mapped_column(Text, default="")
    outcome: Mapped[str] = mapped_column(String(20), default="pending")
    outcome_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    follow_up_count: Mapped[int] = mapped_column(Integer, default=0)
    last_reply_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    batch_id: Mapped[str | None] = mapped_column(String(36), index=True)
    email_to: Mapped[str] = mapped_column(String(320), default="")
    subject: Mapped[str] = mapped_column(String(500), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    cover_letter: Mapped[str | None] = mapped_column(Text)
    cv_suggestions: Mapped[list | None] = mapped_column(JSON)
    job_description: Mapped[str | None] = mapped_column(Text)
    review_reasons: Mapped[list] = mapped_column(JSON, default=list)
    message_id: Mapped[str] = mapped_column(String(255), default="", index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Opportunity(TimestampMixin, Base):
    """A target: company-only spontaneous applications are first-class —
    every field except the company is optional."""

    __tablename__ = "opportunities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    company_id: Mapped[str] = mapped_column(ForeignKey("companies.id"), index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    description_text: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String(1000), default="")
    location: Mapped[str] = mapped_column(String(255), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(20), default="manual")


class ResearchBrief(TimestampMixin, Base):
    """Per-opportunity research with per-fact provenance (source, url,
    retrieved_at, confidence). Facts are never invented; when the provider
    cannot establish a fact it is simply absent."""

    __tablename__ = "research_briefs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    opportunity_id: Mapped[str] = mapped_column(
        ForeignKey("opportunities.id"), unique=True
    )
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    facts: Mapped[list] = mapped_column(JSON, default=list)
    fit_points: Mapped[list] = mapped_column(JSON, default=list)
    provider: Mapped[str] = mapped_column(String(30), default="none")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)


class MatchReport(TimestampMixin, Base):
    """Fit analysis per application (spec §6 stage 3)."""

    __tablename__ = "match_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    application_id: Mapped[str] = mapped_column(
        ForeignKey("applications.id"), unique=True
    )
    score: Mapped[int | None] = mapped_column(Integer)
    strengths: Mapped[list] = mapped_column(JSON, default=list)
    gaps: Mapped[list] = mapped_column(JSON, default=list)
    missing_keywords: Mapped[list] = mapped_column(JSON, default=list)
    model: Mapped[str] = mapped_column(String(60), default="")


class CompanyProfile(TimestampMixin, Base):
    """Global research cache keyed by domain — one research serves all users."""

    __tablename__ = "company_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    domain: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    brief: Mapped[dict] = mapped_column(JSON, default=dict)
    sources: Mapped[list] = mapped_column(JSON, default=list)
    refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Event(TimestampMixin, Base):
    """Merged activity + learning log (V0 learning_feedback, now relational).

    `weight` carries the V0 signal design: sent +1.0, delivered +1.5,
    replied +4.0, soft_bounce -0.75, failed_send -1.0, hard_bounce -3.0.
    Aggregating weight over (domain, pattern) reproduces the V0 learning
    boosts across all users without storing anything person-derived.
    """

    __tablename__ = "events"
    __table_args__ = (Index("ix_events_domain_pattern", "domain", "email_pattern"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    application_id: Mapped[str | None] = mapped_column(
        ForeignKey("applications.id"), index=True
    )
    type: Mapped[str] = mapped_column(String(30), index=True)
    weight: Mapped[float] = mapped_column(Float, default=0.0)
    domain: Mapped[str] = mapped_column(String(255), default="")
    email_pattern: Mapped[str] = mapped_column(String(30), default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class EmailPattern(TimestampMixin, Base):
    """Verified/curated/learned pattern knowledge. user_id NULL = global seed
    (the V0 curated dictionaries migrate here)."""

    __tablename__ = "email_patterns"
    __table_args__ = (UniqueConstraint("user_id", "domain", "pattern"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    domain: Mapped[str] = mapped_column(String(255), index=True)
    pattern: Mapped[str] = mapped_column(String(30))
    confidence: Mapped[float] = mapped_column(Float, default=0.95)
    source: Mapped[str] = mapped_column(String(30), default="curated_v0")
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)


class Suppression(TimestampMixin, Base):
    """Addresses/domains we must never email again (bounce, unsubscribe, manual)."""

    __tablename__ = "suppressions"
    __table_args__ = (UniqueConstraint("user_id", "value"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    value: Mapped[str] = mapped_column(String(320))
    reason: Mapped[str] = mapped_column(String(30), default="manual")


class MailboxSettings(TimestampMixin, Base):
    """Per-user Gmail connection (app password, encrypted at rest) + safety rails."""

    __tablename__ = "mailbox_settings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True)
    smtp_host: Mapped[str] = mapped_column(String(255), default="smtp.gmail.com")
    smtp_port: Mapped[int] = mapped_column(Integer, default=587)
    imap_host: Mapped[str] = mapped_column(String(255), default="imap.gmail.com")
    username: Mapped[str] = mapped_column(String(320), default="")
    password_encrypted: Mapped[str] = mapped_column(Text, default="")
    from_name: Mapped[str] = mapped_column(String(255), default="")
    daily_send_cap: Mapped[int] = mapped_column(Integer, default=20)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
    last_imap_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Job(TimestampMixin, Base):
    """Postgres-backed background job queue (no Celery/Redis at this scale)."""

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_status_run_after", "status", "run_after"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    run_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(Text, default="")
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AiRun(TimestampMixin, Base):
    """Every LLM call metered from day one — cost per user is a launch metric."""

    __tablename__ = "ai_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    application_id: Mapped[str | None] = mapped_column(ForeignKey("applications.id"))
    kind: Mapped[str] = mapped_column(String(30))
    model: Mapped[str] = mapped_column(String(60), default="")
    prompt_version: Mapped[str] = mapped_column(String(20), default="")
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_cents: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
