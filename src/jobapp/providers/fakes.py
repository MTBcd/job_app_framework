"""Deterministic fake providers for tests and the local demo.

Rules the fakes share with real adapters: never invent candidate facts,
never invent company facts — outputs are assembled verbatim from inputs,
and everything is reproducible.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from jobapp.providers import (
    AiUsage,
    OutboundMessage,
    ResearchFact,
    ResearchResult,
    SendResult,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class FakeResearchProvider:
    """Builds a brief strictly from what it was given (company name, domain,
    JD text). Low confidence when only a name is available — mirroring how
    the real provider must degrade instead of hallucinating."""

    def research(
        self, *, company_name: str, domain: str, opportunity_title: str,
        job_description: str,
    ) -> ResearchResult:
        facts: list[ResearchFact] = []
        summary: dict = {"company": company_name}
        fit_points: list[str] = []

        if domain:
            facts.append(
                ResearchFact(
                    fact=f"{company_name} operates the domain {domain}.",
                    source="domain_resolution",
                    source_url=f"https://{domain}",
                    retrieved_at=_now_iso(),
                    confidence=0.9,
                )
            )
        if job_description:
            keywords = sorted(
                {
                    word.strip(".,()").lower()
                    for word in job_description.split()
                    if len(word) > 6
                }
            )[:8]
            summary["jd_keywords"] = keywords
            facts.append(
                ResearchFact(
                    fact=f"The job description emphasises: {', '.join(keywords)}.",
                    source="job_description",
                    retrieved_at=_now_iso(),
                    confidence=0.95,
                )
            )
            fit_points.append(f"Role '{opportunity_title}' matches stated keywords.")

        confidence = 0.8 if facts else 0.2
        return ResearchResult(
            summary=summary,
            facts=facts,
            fit_points=fit_points,
            provider="fake",
            confidence=confidence,
        )


class FakeAIProvider:
    """Deterministic structured outputs assembled from inputs only."""

    def parse_cv(self, cv_text: str) -> tuple[dict, AiUsage]:
        lines = [line.strip() for line in cv_text.splitlines() if line.strip()]
        profile = {
            "identity": {"name": lines[0] if lines else ""},
            "skills": sorted(
                {
                    token.strip(".,")
                    for token in cv_text.replace("/", " ").split()
                    if token[:1].isupper() and len(token) > 2
                }
            )[:15],
            "experience": [],
            "education": [],
            "languages": [],
            "certifications": [],
            "seniority": "unknown",
            "summary_source": "fake_parser",
        }
        return profile, AiUsage(model="fake", tokens_in=len(cv_text) // 4)

    def personalization_plan(self, inputs: dict) -> tuple[dict, AiUsage]:
        profile = inputs.get("profile", {})
        research = inputs.get("research", {})
        contact = inputs.get("contact", {})
        plan = {
            "relevance": f"Candidate skills {profile.get('skills', [])[:3]} relate to "
                         f"{inputs.get('company_name', '')}",
            "experiences_to_mention": profile.get("skills", [])[:2],
            "company_facts_to_use": [
                fact["fact"] for fact in research.get("facts", [])
            ][:2],
            "contact_reason": contact.get("rationale", ""),
            "call_to_action": "short_intro_call",
            "do_not_mention": ["salary", "unverified_company_claims"],
        }
        return plan, AiUsage(model="fake")

    def tailored_email(self, inputs: dict, plan: dict) -> tuple[dict, AiUsage]:
        company = inputs.get("company_name", "")
        contact_name = inputs.get("contact", {}).get("first_name", "") or "there"
        title = inputs.get("opportunity_title", "")
        role_clause = f" regarding {title}" if title else ""
        facts = plan.get("company_facts_to_use", [])
        fact_clause = f" I noted that {facts[0].rstrip('.')}." if facts else ""
        skills = ", ".join(plan.get("experiences_to_mention", []))
        subject = f"{title or 'Introduction'} — {inputs.get('candidate_name', 'Candidate')}"
        body = (
            f"Hi {contact_name},\n\n"
            f"I'm reaching out{role_clause} at {company}.{fact_clause}\n"
            f"My background covers {skills}.\n\n"
            f"Would you be open to a short call?\n"
        )
        return {"subject": subject, "body": body}, AiUsage(model="fake")


class FakeEmailProvider:
    """Records outbound messages so tests and the demo can assert on the
    EXACT content handed to the transport."""

    _shared: FakeEmailProvider | None = None

    def __init__(self) -> None:
        self.sent: list[OutboundMessage] = []

    @classmethod
    def shared(cls) -> FakeEmailProvider:
        if cls._shared is None:
            cls._shared = cls()
        return cls._shared

    @classmethod
    def reset(cls) -> None:
        cls._shared = None

    def send(self, message: OutboundMessage) -> SendResult:
        self.sent.append(message)
        return SendResult(message_id=f"<{uuid.uuid4()}@fake.jobapp>", provider="fake")
