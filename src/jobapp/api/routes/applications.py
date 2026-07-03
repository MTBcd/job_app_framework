"""Applications API (spec §8)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from jobapp.api.deps import CurrentUser, DbSession
from jobapp.db.models import Application, Company, EmailCandidate
from jobapp.services.applications import (
    DuplicateApplication,
    PlanLimitReached,
    create_application,
)

router = APIRouter(prefix="/applications", tags=["applications"])


class ApplicationCreate(BaseModel):
    company_name: str = Field(min_length=1, max_length=255)
    role: str = ""
    jd_text: str = ""
    jd_url: str = ""
    contact_name: str = ""
    contact_title: str = ""
    tone: str = ""


class CandidateOut(BaseModel):
    email: str
    pattern: str
    confidence: float
    reasoning: list
    is_selected: bool


class ApplicationOut(BaseModel):
    id: str
    company_name: str
    role: str
    status: str
    pipeline_stage: str
    email_to: str
    subject: str
    body: str
    review_reasons: list
    outcome: str
    candidates: list[CandidateOut] = []


def _to_out(session, application: Application, *, with_candidates: bool) -> ApplicationOut:
    company = session.get(Company, application.company_id)
    role = ""
    if application.job_posting_id:
        from jobapp.db.models import JobPosting

        posting = session.get(JobPosting, application.job_posting_id)
        role = posting.title if posting else ""
    candidates: list[CandidateOut] = []
    if with_candidates and application.contact_id:
        rows = session.scalars(
            select(EmailCandidate)
            .where(EmailCandidate.contact_id == application.contact_id)
            .order_by(EmailCandidate.confidence.desc())
        ).all()
        candidates = [
            CandidateOut(
                email=row.email,
                pattern=row.pattern,
                confidence=row.confidence,
                reasoning=row.reasoning,
                is_selected=row.is_selected,
            )
            for row in rows
        ]
    return ApplicationOut(
        id=application.id,
        company_name=company.name if company else "",
        role=role,
        status=application.status,
        pipeline_stage=application.pipeline_stage,
        email_to=application.email_to,
        subject=application.subject,
        body=application.body,
        review_reasons=application.review_reasons,
        outcome=application.outcome,
        candidates=candidates,
    )


@router.post("", status_code=201)
def create(payload: ApplicationCreate, user: CurrentUser, session: DbSession) -> dict:
    try:
        application = create_application(
            session,
            user,
            company_name=payload.company_name,
            role=payload.role,
            jd_text=payload.jd_text,
            jd_url=payload.jd_url,
            contact_name=payload.contact_name,
            contact_title=payload.contact_title,
            tone=payload.tone,
        )
    except PlanLimitReached:
        raise HTTPException(
            status_code=402,
            detail="Free plan includes 3 applications. Upgrade to continue.",
        )
    except DuplicateApplication as exc:
        raise HTTPException(
            status_code=409,
            detail={"message": "Company already in your pipeline",
                    "existing_id": exc.existing_id},
        )
    session.commit()
    return {"id": application.id, "status": application.status}


@router.get("")
def list_applications(user: CurrentUser, session: DbSession, status: str = "") -> list[ApplicationOut]:
    statement = select(Application).where(Application.user_id == user.id)
    if status:
        statement = statement.where(Application.status == status)
    statement = statement.order_by(Application.updated_at.desc())
    return [
        _to_out(session, row, with_candidates=False)
        for row in session.scalars(statement).all()
    ]


@router.get("/{application_id}")
def get_application(application_id: str, user: CurrentUser, session: DbSession) -> ApplicationOut:
    application = session.get(Application, application_id)
    if application is None or application.user_id != user.id:
        raise HTTPException(status_code=404, detail="application not found")
    return _to_out(session, application, with_candidates=True)


@router.get("/{application_id}/status")
def get_status(application_id: str, user: CurrentUser, session: DbSession) -> dict:
    application = session.get(Application, application_id)
    if application is None or application.user_id != user.id:
        raise HTTPException(status_code=404, detail="application not found")
    return {"status": application.status, "pipeline_stage": application.pipeline_stage}
