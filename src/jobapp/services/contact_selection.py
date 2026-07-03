"""Contextual contact selection with visible reasoning (spec: never hide why).

Deterministic scoring — no LLM. Components:
  role_relevance          title overlaps the opportunity's role/department words
  recruiting_responsibility  recruiter/talent/HR titles score for any opportunity
  seniority_appropriateness  founders/execs only appropriate for small companies
  data_confidence         full name + title present
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from jobapp.db.models import Contact, Opportunity

RECRUITING_WORDS = {"recruit", "talent", "people", "hr", "human resources"}
EXEC_WORDS = {"ceo", "cto", "coo", "founder", "co-founder", "president", "chief"}
LEAD_WORDS = {"head", "lead", "director", "manager", "vp", "principal"}

SMALL_COMPANY_MAX = 50  # founders are reasonable targets below this size


@dataclass
class ScoredContact:
    contact: Contact
    score: float
    components: dict
    rationale: str


def _title_words(title: str) -> set[str]:
    return {word.strip(".,()").lower() for word in title.split() if word}


def score_contact(
    contact: Contact,
    opportunity: Opportunity,
    company_size: int | None,
) -> ScoredContact:
    title_lower = (contact.title or "").lower()
    words = _title_words(contact.title or "")
    opportunity_words = _title_words(opportunity.title or "")

    components: dict[str, float] = {}

    is_recruiter = any(word in title_lower for word in RECRUITING_WORDS)
    components["recruiting_responsibility"] = 0.45 if is_recruiter else 0.0

    overlap = words & opportunity_words - {"of", "and"}
    components["role_relevance"] = min(0.4, 0.2 * len(overlap)) if overlap else 0.0

    is_exec = any(word in words for word in EXEC_WORDS)
    is_lead = any(word in words for word in LEAD_WORDS)
    if is_exec:
        small = company_size is not None and company_size <= SMALL_COMPANY_MAX
        components["seniority_appropriateness"] = 0.35 if small else -0.3
    elif is_lead:
        components["seniority_appropriateness"] = 0.2
    else:
        components["seniority_appropriateness"] = 0.05

    has_name = bool(contact.first_name and contact.last_name)
    components["data_confidence"] = (0.1 if has_name else 0.0) + (
        0.05 if contact.title else 0.0
    )

    score = round(sum(components.values()), 3)

    if is_recruiter:
        reason = f"{contact.title} — owns recruiting for the company"
    elif overlap:
        reason = (
            f"{contact.title} — closest match to the "
            f"'{opportunity.title}' opportunity"
        )
    elif is_exec:
        reason = (
            f"{contact.title} — appropriate because the company is small"
            if components["seniority_appropriateness"] > 0
            else f"{contact.title} — likely too senior for this opportunity"
        )
    else:
        reason = contact.title or "no title information"

    return ScoredContact(
        contact=contact, score=score, components=components, rationale=reason
    )


def select_best_contact(
    session: Session,
    opportunity: Opportunity,
    company_size: int | None = None,
) -> ScoredContact | None:
    contacts = session.scalars(
        select(Contact).where(Contact.company_id == opportunity.company_id)
    ).all()
    if not contacts:
        return None

    scored = sorted(
        (score_contact(contact, opportunity, company_size) for contact in contacts),
        key=lambda item: item.score,
        reverse=True,
    )
    best = scored[0]
    alternatives = len(scored) - 1
    best.rationale = (
        f"Recommended contact: {best.contact.full_name} — {best.contact.title}. "
        f"Selected because: {best.rationale}."
        + (f" ({alternatives} alternative(s) considered.)" if alternatives else "")
    )
    return best
