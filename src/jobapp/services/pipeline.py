"""The application preparation pipeline (product spine):

  research → contact selection → email resolution → personalization plan
  → tailored email → ready_for_review

Providers are injected; deterministic fakes back tests and the demo.
Nothing here sends — sending consumes the approved snapshot only
(services.sending).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from jobapp.company import infer_company_domain
from jobapp.db.models import Application, Company, Opportunity
from jobapp.providers import (
    AIProvider,
    ResearchProvider,
    get_ai_provider,
    get_research_provider,
)
from jobapp.services.contact_selection import select_best_contact
from jobapp.services.email_resolution import resolve_email
from jobapp.services.generation import generate_application_content
from jobapp.services.research import build_research_brief


def prepare_application(
    session: Session,
    application_id: str,
    *,
    research_provider: ResearchProvider | None = None,
    ai_provider: AIProvider | None = None,
) -> Application:
    application = session.get(Application, application_id)
    if application is None:
        raise ValueError(f"application {application_id} not found")
    research_provider = research_provider or get_research_provider()
    ai_provider = ai_provider or get_ai_provider()

    company = session.get(Company, application.company_id)
    opportunity = session.get(Opportunity, application.opportunity_id)
    review_reasons: list[str] = []

    # 1. Domain resolution (V0 engine, curated overrides first)
    application.pipeline_stage = "researching"
    application.status = "researching"
    if not company.domain:
        domain, source = infer_company_domain(company.name)
        company.domain = domain
        company.domain_source = source

    # 2. Research brief with provenance
    brief = build_research_brief(session, opportunity, company, research_provider)
    if brief.confidence < 0.5:
        review_reasons.append("limited_research")

    # 3. Contact selection (contextual, reasoned)
    application.pipeline_stage = "selecting_contact"
    selected = select_best_contact(session, opportunity)
    contact = None
    if selected is None:
        if application.contact_id is None:
            review_reasons.append("no_contact")
    else:
        contact = selected.contact
        application.contact_id = contact.id
        application.contact_rationale = selected.rationale

    # 4. Email resolution (explicit precedence over the V0 engine)
    application.pipeline_stage = "resolving_email"
    if contact is None and application.contact_id is not None:
        from jobapp.db.models import Contact

        contact = session.get(Contact, application.contact_id)
    if contact is not None:
        resolved = resolve_email(session, contact, company)
        application.email_to = resolved.email
        application.email_source = resolved.source
        application.email_pattern = resolved.pattern
        application.email_label = resolved.label
        application.email_confidence = resolved.confidence
        review_reasons += resolved.review_reasons

    # 5. Personalization plan + tailored email
    application.pipeline_stage = "generating"
    generate_application_content(
        session, application, opportunity, company, contact, brief, ai_provider
    )

    # Merge: generation may have appended its own reasons (e.g. fallback).
    appended = [r for r in (application.review_reasons or []) if r not in review_reasons]
    application.review_reasons = review_reasons + appended
    application.pipeline_stage = "done"
    application.status = "ready_for_review"
    session.flush()
    return application


def run_job(session: Session, kind: str, payload: dict) -> None:
    """Worker dispatch table."""
    if kind == "prepare_application":
        prepare_application(session, payload["application_id"])
    else:
        raise ValueError(f"unknown job kind: {kind}")
