"""Minimal server-rendered review UI (local beta).

Deliberately simple: Jinja2 over the existing services, a fixed local beta
user, synchronous pipeline on submit, and the fake email provider for
sending — nothing leaves the machine. Enabled only when APP_ENV=local.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from jobapp.api.deps import DbSession
from jobapp.db.models import (
    Application,
    Company,
    Contact,
    Document,
    Opportunity,
    ResearchBrief,
    User,
)
from jobapp.providers.fakes import FakeEmailProvider
from jobapp.services.applications import DuplicateApplication, create_application
from jobapp.services.pipeline import prepare_application
from jobapp.services.sending import SendBlocked, approve, send
from jobapp.settings import get_settings

router = APIRouter(prefix="/ui", tags=["ui"], include_in_schema=False)
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[2] / "ui_templates")
)

UI_USER_EMAIL = "beta@local"


def _guard_local() -> None:
    if get_settings().app_env != "local":
        raise HTTPException(status_code=404)


def _ui_user(session) -> User:
    _guard_local()
    user = session.scalars(select(User).where(User.email == UI_USER_EMAIL)).first()
    if user is None:
        user = User(clerk_user_id="ui_beta_local", email=UI_USER_EMAIL)
        session.add(user)
        session.commit()
    return user


def _render(request: Request, template: str, context: dict) -> HTMLResponse:
    context.setdefault("ai_real", bool(get_settings().anthropic_api_key))
    return templates.TemplateResponse(request, template, context)


def _display_status(application: Application) -> str:
    if application.status == "sent" and application.message_id.endswith("@fake.jobapp>"):
        return "sent (simulated)"
    return application.status.replace("_", " ")


def _cv_document(session, user: User) -> Document | None:
    return session.scalars(
        select(Document).where(Document.user_id == user.id, Document.kind == "cv")
    ).first()


# --------------------------------------------------------------- dashboard
@router.get("", response_class=HTMLResponse)
def index(request: Request, session: DbSession):
    user = _ui_user(session)
    rows = session.scalars(
        select(Application)
        .where(Application.user_id == user.id)
        .order_by(Application.updated_at.desc())
    ).all()
    applications = []
    for application in rows:
        company = session.get(Company, application.company_id)
        opportunity = (
            session.get(Opportunity, application.opportunity_id)
            if application.opportunity_id else None
        )
        applications.append({
            "id": application.id,
            "company_name": company.name if company else "",
            "role": opportunity.title if opportunity else "",
            "status": application.status,
            "display_status": _display_status(application),
        })
    return _render(request, "index.html", {
        "applications": applications,
        "has_profile": _cv_document(session, user) is not None,
    })


# ----------------------------------------------------------------- profile
_PROFILE_FIELDS = ("target_role", "location", "headline", "experience_summary")


@router.get("/profile", response_class=HTMLResponse)
def profile_form(request: Request, session: DbSession):
    user = _ui_user(session)
    document = _cv_document(session, user)
    parsed = document.parsed_profile if document else {}
    p = {
        "full_name": (parsed.get("identity") or {}).get("name", user.full_name),
        "skills": ", ".join(parsed.get("skills", [])),
        "proof_points": "\n".join(parsed.get("projects", [])),
        "constraints": "\n".join(parsed.get("constraints_or_gaps", [])),
    }
    for field in _PROFILE_FIELDS:
        p[field] = parsed.get(field, "")
    return _render(request, "profile.html", {"p": p})


@router.post("/profile")
def save_profile(
    session: DbSession,
    full_name: str = Form(...),
    target_role: str = Form(""),
    location: str = Form(""),
    headline: str = Form(""),
    experience_summary: str = Form(""),
    skills: str = Form(""),
    proof_points: str = Form(""),
    constraints: str = Form(""),
):
    user = _ui_user(session)
    profile = {
        "identity": {"name": full_name.strip()},
        "target_role": target_role.strip(),
        "location": location.strip(),
        "headline": headline.strip(),
        "experience_summary": experience_summary.strip(),
        "skills": [s.strip() for s in skills.split(",") if s.strip()],
        "projects": [l.strip() for l in proof_points.splitlines() if l.strip()],
        "constraints_or_gaps": [l.strip() for l in constraints.splitlines() if l.strip()],
        "work_experience": [],
        "seniority": "unknown",
        "source": "manual_entry",
    }
    content_text = "\n".join(
        filter(None, [full_name, headline, experience_summary, skills, proof_points])
    )
    document = _cv_document(session, user)
    if document is None:
        document = Document(user_id=user.id, kind="cv")
        session.add(document)
    document.content_text = content_text
    document.parsed_profile = profile
    user.full_name = full_name.strip()
    user.target_roles = [target_role.strip()] if target_role.strip() else []
    session.commit()
    return RedirectResponse("/ui/new", status_code=303)


# ------------------------------------------------------------- opportunity
@router.get("/new", response_class=HTMLResponse)
def opportunity_form(request: Request, session: DbSession):
    _ui_user(session)
    return _render(request, "opportunity.html", {})


@router.post("/opportunity")
def create_opportunity(
    session: DbSession,
    company_name: str = Form(...),
    role: str = Form(""),
    jd_text: str = Form(""),
    notes: str = Form(""),
    contact_name: str = Form(""),
    contact_title: str = Form(""),
    contact_email: str = Form(""),
):
    user = _ui_user(session)
    try:
        application = create_application(
            session, user,
            company_name=company_name, role=role, jd_text=jd_text, notes=notes,
            contact_name=contact_name, contact_title=contact_title,
            contact_email=contact_email,
            enqueue=False,  # pipeline runs inline below
        )
    except DuplicateApplication as exc:
        session.rollback()
        return RedirectResponse(f"/ui/applications/{exc.existing_id}", status_code=303)
    prepare_application(session, application.id)
    session.commit()
    return RedirectResponse(f"/ui/applications/{application.id}", status_code=303)


# ------------------------------------------------------------------ review
def _owned(session, user: User, application_id: str) -> Application:
    application = session.get(Application, application_id)
    if application is None or application.user_id != user.id:
        raise HTTPException(status_code=404)
    return application


@router.get("/applications/{application_id}", response_class=HTMLResponse)
def review(request: Request, application_id: str, session: DbSession, error: str = ""):
    user = _ui_user(session)
    application = _owned(session, user, application_id)
    company = session.get(Company, application.company_id)
    opportunity = (
        session.get(Opportunity, application.opportunity_id)
        if application.opportunity_id else None
    )
    contact = (
        session.get(Contact, application.contact_id)
        if application.contact_id else None
    )
    brief = None
    if opportunity:
        brief = session.scalars(
            select(ResearchBrief).where(ResearchBrief.opportunity_id == opportunity.id)
        ).first()
    plan = application.personalization_plan or {}
    return _render(request, "review.html", {
        "app": application,
        "display_status": _display_status(application),
        "company_name": company.name if company else "",
        "role": opportunity.title if opportunity else "",
        "contact_name": contact.full_name if contact else "",
        "contact_title": contact.title if contact else "",
        "research": brief,
        "strengths": plan.get("candidate_strengths", []),
        "gaps": plan.get("gaps_to_avoid_overclaiming", []),
        "error": error,
    })


@router.post("/applications/{application_id}/save")
def save_edits(
    application_id: str, session: DbSession,
    subject: str = Form(""), body: str = Form(""),
):
    user = _ui_user(session)
    application = _owned(session, user, application_id)
    if application.status not in {"sent", "replied"}:
        application.subject = subject
        application.body = body
        session.commit()
    return RedirectResponse(f"/ui/applications/{application_id}", status_code=303)


@router.post("/applications/{application_id}/approve")
def approve_application(application_id: str, session: DbSession):
    user = _ui_user(session)
    application = _owned(session, user, application_id)
    try:
        approve(session, application)
        session.commit()
    except SendBlocked as exc:
        session.rollback()
        return RedirectResponse(
            f"/ui/applications/{application_id}?error={exc.reason}", status_code=303
        )
    return RedirectResponse(f"/ui/applications/{application_id}", status_code=303)


@router.post("/applications/{application_id}/send")
def send_application(application_id: str, session: DbSession):
    user = _ui_user(session)
    application = _owned(session, user, application_id)
    try:
        # Simulation only in this milestone: always the fake transport.
        send(session, application, user, provider=FakeEmailProvider.shared())
        session.commit()
    except SendBlocked as exc:
        session.rollback()
        return RedirectResponse(
            f"/ui/applications/{application_id}?error={exc.reason}", status_code=303
        )
    return RedirectResponse(f"/ui/applications/{application_id}", status_code=303)


# -------------------------------------------------------------------- demo
@router.post("/demo")
def demo(session: DbSession):
    """Seed profile + contacts + one spontaneous opportunity, run the
    pipeline, land on review. No external services required."""
    user = _ui_user(session)
    if _cv_document(session, user) is None:
        session.add(Document(
            user_id=user.id, kind="cv",
            content_text="Jane Doe — Senior Data Scientist",
            parsed_profile={
                "identity": {"name": "Jane Doe"},
                "target_role": "Data Scientist",
                "headline": "Senior data scientist, forecasting and ML in production",
                "experience_summary": "5 years building forecasting models",
                "skills": ["Python", "Machine Learning", "SQL", "Forecasting"],
                "projects": ["built demand forecasting used across 40 stores"],
                "constraints_or_gaps": ["no healthcare industry experience"],
                "work_experience": [], "seniority": "senior",
                "source": "demo_seed",
            },
        ))
        user.full_name = "Jane Doe"
        session.flush()

    try:
        application = create_application(
            session, user, company_name="Northwind Analytics",
            notes="spontaneous demo application", enqueue=False,
        )
    except DuplicateApplication as exc:
        session.rollback()
        return RedirectResponse(f"/ui/applications/{exc.existing_id}", status_code=303)
    for first, last, title in [("Carl", "Chief", "CEO"),
                               ("Rita", "Recruit", "Head of Talent Acquisition")]:
        session.add(Contact(
            user_id=user.id, company_id=application.company_id,
            first_name=first, last_name=last, full_name=f"{first} {last}",
            title=title,
        ))
    session.flush()
    prepare_application(session, application.id)
    session.commit()
    return RedirectResponse(f"/ui/applications/{application.id}", status_code=303)
