"""Research brief construction with per-fact provenance (spec: never invent)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from jobapp.db.models import Company, Opportunity, ResearchBrief
from jobapp.providers import ResearchProvider


def build_research_brief(
    session: Session,
    opportunity: Opportunity,
    company: Company,
    provider: ResearchProvider,
) -> ResearchBrief:
    existing = session.scalars(
        select(ResearchBrief).where(ResearchBrief.opportunity_id == opportunity.id)
    ).first()
    if existing is not None:
        return existing

    result = provider.research(
        company_name=company.name,
        domain=company.domain,
        opportunity_title=opportunity.title,
        job_description=opportunity.description_text,
    )
    brief = ResearchBrief(
        opportunity_id=opportunity.id,
        summary=result.summary,
        facts=[fact.to_dict() for fact in result.facts],
        fit_points=result.fit_points,
        provider=result.provider,
        confidence=result.confidence,
    )
    session.add(brief)
    session.flush()
    return brief
