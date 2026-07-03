"""The application preparation pipeline (spec §9).

Runs the V0 engine for the stages that need no LLM (domain resolution,
email inference with confidence + reasoning) and honest non-AI fallbacks
for generation until the AI provider is configured (spec §10: the app
never dead-ends on a missing/failed LLM).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from jobapp.company import infer_company_domain
from jobapp.db.models import Application, Company, Contact, EmailCandidate, MatchReport
from jobapp.email_inference import REVIEW_CONFIDENCE_THRESHOLD, score_candidates
from jobapp.settings import get_settings

FALLBACK_SUBJECT = "Application — {role_or_default} at {company}"
FALLBACK_BODY = """Dear {salutation_name},

I am writing to express my interest in {role_or_default} opportunities at {company}.

[Copilot AI drafting is not configured yet — this is a neutral template.
Edit freely, or configure the AI provider to generate a tailored draft.]

Kind regards,
{sender_name}
"""


def _resolve_domain(session: Session, application: Application) -> Company:
    company = session.get(Company, application.company_id)
    if not company.domain:
        domain, source = infer_company_domain(company.name)
        company.domain = domain
        company.domain_source = source
    return company


def _infer_addresses(
    session: Session, application: Application, company: Company
) -> tuple[list[str], str]:
    """Returns (review_reasons, selected_email)."""
    reasons: list[str] = []
    if application.contact_id is None:
        return (["no_contact"], "")

    contact = session.get(Contact, application.contact_id)
    if not company.domain:
        return (["missing_company_domain"], "")

    candidates = score_candidates(
        contact.first_name,
        contact.last_name,
        company.domain,
        domain_source=company.domain_source,
    )
    if not candidates:
        return (["no_email_candidates"], "")

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
    if top.confidence < REVIEW_CONFIDENCE_THRESHOLD:
        reasons.append("low_email_confidence")
    if company.domain_source == "heuristic_company_to_com":
        reasons.append("heuristic_domain")
    return (reasons, top.email)


def _generate_documents(
    session: Session, application: Application, company: Company
) -> list[str]:
    settings = get_settings()
    posting_title = ""
    if application.job_posting_id:
        from jobapp.db.models import JobPosting

        posting = session.get(JobPosting, application.job_posting_id)
        posting_title = posting.title if posting else ""

    if not settings.anthropic_api_key:
        salutation_name = "Hiring Team"
        if application.contact_id:
            contact = session.get(Contact, application.contact_id)
            if contact.first_name:
                salutation_name = f"{contact.first_name} {contact.last_name}".strip()
        values = {
            "company": company.name,
            "role_or_default": posting_title or "relevant",
            "salutation_name": salutation_name,
            "sender_name": "",
        }
        application.subject = FALLBACK_SUBJECT.format(**values)
        application.body = FALLBACK_BODY.format(**values)
        session.add(
            MatchReport(application_id=application.id, score=None, model="none")
        )
        return ["ai_not_configured"]

    raise NotImplementedError("AI generation lands in Milestone 3")


def prepare_application(session: Session, application_id: str) -> Application:
    application = session.get(Application, application_id)
    if application is None:
        raise ValueError(f"application {application_id} not found")

    application.pipeline_stage = "researching"
    company = _resolve_domain(session, application)

    application.pipeline_stage = "inferring"
    review_reasons, selected = _infer_addresses(session, application, company)
    application.email_to = selected

    application.pipeline_stage = "generating"
    review_reasons += _generate_documents(session, application, company)

    application.review_reasons = review_reasons
    application.pipeline_stage = "done"
    application.status = "needs_review"
    session.flush()
    return application


def run_job(session: Session, kind: str, payload: dict) -> None:
    """Worker dispatch table."""
    if kind == "prepare_application":
        prepare_application(session, payload["application_id"])
    else:
        raise ValueError(f"unknown job kind: {kind}")
