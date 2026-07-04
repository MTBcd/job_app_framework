"""Personalization plan + tailored email generation (spec: plan first, then
email; every run metered into ai_runs; inputs assembled from persisted
structured data only — the model is never asked to invent)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from jobapp.db.models import (
    AiRun,
    Application,
    Company,
    Contact,
    Document,
    Opportunity,
    ResearchBrief,
)
from jobapp.providers import AIProvider


def _record_run(
    session: Session, application: Application, kind: str, usage
) -> None:
    session.add(
        AiRun(
            user_id=application.user_id,
            application_id=application.id,
            kind=kind,
            model=usage.model,
            prompt_version=usage.prompt_version,
            tokens_in=usage.tokens_in,
            tokens_out=usage.tokens_out,
            cost_cents=usage.cost_cents,
            latency_ms=usage.latency_ms,
        )
    )


def generate_application_content(
    session: Session,
    application: Application,
    opportunity: Opportunity,
    company: Company,
    contact: Contact | None,
    brief: ResearchBrief,
    ai: AIProvider,
) -> None:
    document = session.scalars(
        select(Document).where(
            Document.user_id == application.user_id, Document.kind == "cv"
        )
    ).first()
    profile = document.parsed_profile if document else {}
    candidate_name = (profile.get("identity") or {}).get("name", "")

    inputs = {
        "candidate_name": candidate_name,
        "profile": profile,
        "company_name": company.name,
        "opportunity_title": opportunity.title,
        "job_description": opportunity.description_text,
        "research": {"summary": brief.summary, "facts": brief.facts,
                     "fit_points": brief.fit_points,
                     "confidence": brief.confidence},
        "contact": {
            "first_name": contact.first_name if contact else "",
            "title": contact.title if contact else "",
            "rationale": application.contact_rationale,
        },
        "tone": application.tone,
    }

    from jobapp.providers import AiProviderError

    try:
        plan, plan_usage = ai.personalization_plan(inputs)
        _record_run(session, application, "personalization_plan", plan_usage)
        application.personalization_plan = plan

        email, email_usage = ai.tailored_email(inputs, plan)
        _record_run(session, application, "tailored_email", email_usage)
    except AiProviderError:
        # Never dead-end on a provider failure: fall back to the
        # deterministic fake and flag the application for review.
        from jobapp.providers.fakes import FakeAIProvider

        fake = FakeAIProvider()
        plan, _ = fake.personalization_plan(inputs)
        application.personalization_plan = plan
        email, _ = fake.tailored_email(inputs, plan)
        reasons = list(application.review_reasons or [])
        if "ai_generation_failed" not in reasons:
            application.review_reasons = reasons + ["ai_generation_failed"]

    application.subject = email["subject"]
    application.body = email["body"]
    session.flush()
