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
    email_source: str = ""
    email_label: str = ""
    email_confidence: float = 0.0
    contact_rationale: str = ""
    subject: str
    body: str
    review_reasons: list
    outcome: str
    reply_preview: str = ""
    personalization_plan: dict = {}
    research: dict | None = None
    candidates: list[CandidateOut] = []


def _to_out(session, application: Application, *, with_candidates: bool) -> ApplicationOut:
    company = session.get(Company, application.company_id)
    role = ""
    if application.opportunity_id:
        from jobapp.db.models import Opportunity

        opportunity = session.get(Opportunity, application.opportunity_id)
        role = opportunity.title if opportunity else ""
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
    research = None
    if with_candidates and application.opportunity_id:
        from jobapp.db.models import ResearchBrief

        brief = session.scalars(
            select(ResearchBrief).where(
                ResearchBrief.opportunity_id == application.opportunity_id
            )
        ).first()
        if brief is not None:
            research = {
                "summary": brief.summary,
                "facts": brief.facts,
                "fit_points": brief.fit_points,
                "provider": brief.provider,
                "confidence": brief.confidence,
            }
    return ApplicationOut(
        id=application.id,
        company_name=company.name if company else "",
        role=role,
        status=application.status,
        pipeline_stage=application.pipeline_stage,
        email_to=application.email_to,
        email_source=application.email_source,
        email_label=application.email_label,
        email_confidence=application.email_confidence,
        contact_rationale=application.contact_rationale,
        subject=application.subject,
        body=application.body,
        review_reasons=application.review_reasons,
        outcome=application.outcome,
        reply_preview=application.reply_preview,
        personalization_plan=application.personalization_plan
        if with_candidates
        else {},
        research=research,
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


class ApplicationEdit(BaseModel):
    subject: str | None = None
    body: str | None = None


def _owned(application_id: str, user, session) -> Application:
    application = session.get(Application, application_id)
    if application is None or application.user_id != user.id:
        raise HTTPException(status_code=404, detail="application not found")
    return application


@router.patch("/{application_id}")
def edit_application(
    application_id: str, payload: ApplicationEdit, user: CurrentUser, session: DbSession
) -> ApplicationOut:
    application = _owned(application_id, user, session)
    if application.status in {"sent", "replied", "positive_reply"}:
        raise HTTPException(status_code=409, detail="already sent")
    if payload.subject is not None:
        application.subject = payload.subject
    if payload.body is not None:
        application.body = payload.body
    session.commit()
    return _to_out(session, application, with_candidates=False)


@router.post("/{application_id}/approve")
def approve_application(
    application_id: str, payload: ApplicationEdit, user: CurrentUser, session: DbSession
) -> dict:
    from jobapp.services.sending import SendBlocked, approve

    application = _owned(application_id, user, session)
    try:
        approve(session, application, subject=payload.subject, body=payload.body)
    except SendBlocked as exc:
        raise HTTPException(status_code=409, detail=exc.reason)
    session.commit()
    return {"status": application.status, "approved_at": str(application.approved_at)}


@router.post("/{application_id}/send")
def send_application(
    application_id: str, user: CurrentUser, session: DbSession
) -> dict:
    from jobapp.services.sending import SendBlocked, send

    application = _owned(application_id, user, session)
    try:
        send(session, application, user)
    except SendBlocked as exc:
        raise HTTPException(status_code=409, detail=exc.reason)
    session.commit()
    return {"status": application.status, "message_id": application.message_id}


@router.get("/{application_id}/status")
def get_status(application_id: str, user: CurrentUser, session: DbSession) -> dict:
    application = session.get(Application, application_id)
    if application is None or application.user_id != user.id:
        raise HTTPException(status_code=404, detail="application not found")
    return {"status": application.status, "pipeline_stage": application.pipeline_stage}
