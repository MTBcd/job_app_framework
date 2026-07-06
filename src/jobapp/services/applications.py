"""Application creation and retrieval (spec §8-9)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from jobapp.cleaning import company_display_name, normalize_company_name
from jobapp.contacts import parse_full_name
from jobapp.db.models import Application, Company, Contact, Opportunity, User
from jobapp.services import queue

FREE_PLAN_APPLICATION_CAP = 3


class PlanLimitReached(Exception):
    pass


class DuplicateApplication(Exception):
    def __init__(self, existing_id: str) -> None:
        self.existing_id = existing_id
        super().__init__(f"duplicate of application {existing_id}")


def _get_or_create_company(session: Session, user: User, name: str) -> Company:
    normalized = normalize_company_name(name)
    company = session.scalars(
        select(Company).where(
            Company.user_id == user.id, Company.name_normalized == normalized
        )
    ).first()
    if company is None:
        company = Company(
            user_id=user.id,
            name=company_display_name(name),
            name_normalized=normalized,
        )
        session.add(company)
        session.flush()
    return company


def create_application(
    session: Session,
    user: User,
    *,
    company_name: str,
    role: str = "",
    jd_text: str = "",
    jd_url: str = "",
    location: str = "",
    notes: str = "",
    contact_name: str = "",
    contact_title: str = "",
    tone: str = "",
) -> Application:
    if user.plan == "free":
        count = len(
            session.scalars(
                select(Application.id).where(Application.user_id == user.id)
            ).all()
        )
        if count >= FREE_PLAN_APPLICATION_CAP:
            raise PlanLimitReached

    company = _get_or_create_company(session, user, company_name)

    existing = session.scalars(
        select(Application).where(
            Application.user_id == user.id,
            Application.company_id == company.id,
            Application.status.notin_(["archived"]),
        )
    ).first()
    if existing is not None and (role or "") == "":
        raise DuplicateApplication(existing.id)

    # Company-only spontaneous applications are first-class: the opportunity
    # row always exists, its JD/url/title fields may all be empty.
    opportunity = Opportunity(
        user_id=user.id,
        company_id=company.id,
        title=role,
        description_text=jd_text,
        url=jd_url,
        location=location,
        notes=notes,
        source="url" if jd_url and not jd_text else "manual",
    )
    session.add(opportunity)
    session.flush()

    contact = None
    if contact_name:
        parsed = parse_full_name(contact_name)
        # One person = one contact row per company (V0 audit lesson: identity
        # collapse/duplication corrupts dedupe and learning).
        contact = session.scalars(
            select(Contact).where(
                Contact.user_id == user.id,
                Contact.company_id == company.id,
                Contact.first_name == parsed["first_name"],
                Contact.last_name == parsed["last_name"],
            )
        ).first()
        if contact is None:
            contact = Contact(
                user_id=user.id,
                company_id=company.id,
                first_name=parsed["first_name"],
                last_name=parsed["last_name"],
                full_name=parsed["full_name_clean"],
                title=contact_title,
                source="manual",
                name_parse_warning=parsed["name_parse_warning"],
            )
            session.add(contact)
            session.flush()

    application = Application(
        user_id=user.id,
        company_id=company.id,
        contact_id=contact.id if contact else None,
        opportunity_id=opportunity.id,
        status="researching",
        pipeline_stage="queued",
        tone=tone or user.tone_default,
    )
    session.add(application)
    session.flush()

    queue.enqueue(
        session,
        "prepare_application",
        {"application_id": application.id},
        user_id=user.id,
    )
    return application
