"""Email resolution behind a clean interface over the V0 inference engine.

Explicit precedence (spec):
  1. provided        — the user gave us the address
  2. verified        — externally verified (verification adapters post-slice)
  3. curated_pattern — EmailPattern rows with source curated/verified
  4. learned_pattern — aggregated safe learning signals (domain+pattern events)
  5. heuristic       — V0 candidate generation + priors

The UI label never overstates certainty (spec: an inferred address is never
presented as verified).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from jobapp.cleaning import is_valid_email
from jobapp.db.models import Company, Contact, EmailCandidate, EmailPattern, Event
from jobapp.email_inference import REVIEW_CONFIDENCE_THRESHOLD, score_candidates

LABELS = {
    "provided": "Verified",           # user-supplied address
    "verified": "Verified",
    "curated_pattern": "Known pattern",
    "learned_pattern": "Known pattern",
    "heuristic_high": "High-confidence inference",
    "heuristic_low": "Low-confidence inference",
    "none": "Manual review required",
}


@dataclass
class ResolvedEmail:
    email: str = ""
    source: str = "none"
    pattern: str = ""
    confidence: float = 0.0
    reasoning: list = field(default_factory=list)
    verification_status: str = "unverified"
    label: str = LABELS["none"]
    review_reasons: list = field(default_factory=list)


def _curated_pattern(session: Session, domain: str) -> dict | None:
    row = session.scalars(
        select(EmailPattern)
        .where(EmailPattern.domain == domain)
        .where(EmailPattern.user_id.is_(None))
        .order_by(EmailPattern.confidence.desc())
    ).first()
    if row is None:
        return None
    return {"email_pattern": row.pattern, "domain": domain, "confidence": row.confidence}


def _learned_pattern(session: Session, domain: str) -> dict | None:
    """Safe learning aggregation: domain+pattern weights only (privacy boundary:
    no names, no addresses, no cross-user person data — see docs/api.md)."""
    rows = session.execute(
        select(Event.email_pattern, func.sum(Event.weight))
        .where(Event.domain == domain, Event.email_pattern != "")
        .group_by(Event.email_pattern)
    ).all()
    positive = [(pattern, total) for pattern, total in rows if total and total > 0]
    if not positive:
        return None
    best_pattern, best_total = max(positive, key=lambda item: item[1])
    total = sum(total for _, total in positive)
    return {
        "pattern": best_pattern,
        "share": best_total / total if total else 0.0,
        "count": int(best_total),
    }


def resolve_email(
    session: Session,
    contact: Contact,
    company: Company,
    provided_email: str = "",
) -> ResolvedEmail:
    if provided_email and is_valid_email(provided_email):
        return ResolvedEmail(
            email=provided_email.strip(),
            source="provided",
            pattern="provided",
            confidence=1.0,
            reasoning=["user_provided_address"],
            verification_status="user_provided",
            label=LABELS["provided"],
        )

    if not company.domain:
        return ResolvedEmail(review_reasons=["missing_company_domain"])

    curated = _curated_pattern(session, company.domain)
    learned = _learned_pattern(session, company.domain)

    candidates = score_candidates(
        contact.first_name,
        contact.last_name,
        company.domain,
        known_pattern_info=learned,
        domain_source=company.domain_source,
        verified_pattern_info=curated,
    )
    if not candidates:
        return ResolvedEmail(review_reasons=["no_email_candidates"])

    # Idempotent per contact: a fresh resolution replaces prior candidates.
    session.execute(
        delete(EmailCandidate).where(EmailCandidate.contact_id == contact.id)
    )
    for rank, candidate in enumerate(candidates):
        session.add(
            EmailCandidate(
                contact_id=contact.id,
                email=candidate.email,
                pattern=candidate.pattern,
                confidence=round(candidate.confidence, 3),
                reasoning=candidate.reasoning,
                is_selected=rank == 0,
            )
        )

    top = candidates[0]
    if curated and top.pattern == curated["email_pattern"]:
        source = "curated_pattern"
    elif learned and top.pattern == learned["pattern"]:
        source = "learned_pattern"
    else:
        source = "heuristic"

    review_reasons: list[str] = []
    if top.confidence < REVIEW_CONFIDENCE_THRESHOLD and source == "heuristic":
        review_reasons.append("low_email_confidence")
    if company.domain_source == "heuristic_company_to_com":
        review_reasons.append("heuristic_domain")

    if source == "heuristic":
        label = (
            LABELS["heuristic_high"]
            if top.confidence >= REVIEW_CONFIDENCE_THRESHOLD
            else LABELS["heuristic_low"]
        )
    else:
        label = LABELS[source]

    return ResolvedEmail(
        email=top.email,
        source=source,
        pattern=top.pattern,
        confidence=round(top.confidence, 3),
        reasoning=top.reasoning,
        verification_status="unverified",
        label=label,
        review_reasons=review_reasons,
    )
