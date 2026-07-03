"""Provider ports (hexagonal seams) and factories.

Domain services depend only on these Protocols. Deterministic fakes back
tests and the demo; real adapters (Anthropic, web research, Gmail OAuth)
plug in without touching domain code. Factories return the fake whenever
the corresponding credential is absent — the app never dead-ends.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from jobapp.settings import get_settings


# ---------------------------------------------------------------- research
@dataclass
class ResearchFact:
    fact: str
    source: str            # e.g. "company_website", "job_description", "fake"
    source_url: str = ""
    retrieved_at: str = ""  # ISO timestamp
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class ResearchResult:
    summary: dict = field(default_factory=dict)   # what/industry/model/products…
    facts: list[ResearchFact] = field(default_factory=list)
    fit_points: list[str] = field(default_factory=list)
    provider: str = "none"
    confidence: float = 0.0


class ResearchProvider(Protocol):
    def research(
        self, *, company_name: str, domain: str, opportunity_title: str,
        job_description: str,
    ) -> ResearchResult: ...


# ---------------------------------------------------------------------- ai
@dataclass
class AiUsage:
    model: str = "fake"
    tokens_in: int = 0
    tokens_out: int = 0
    cost_cents: float = 0.0


class AIProvider(Protocol):
    def parse_cv(self, cv_text: str) -> tuple[dict, AiUsage]: ...

    def personalization_plan(self, inputs: dict) -> tuple[dict, AiUsage]: ...

    def tailored_email(
        self, inputs: dict, plan: dict
    ) -> tuple[dict, AiUsage]: ...  # -> {"subject": str, "body": str}


# ------------------------------------------------------------------- email
@dataclass
class OutboundMessage:
    to_email: str
    subject: str
    body: str
    from_name: str = ""
    from_email: str = ""


@dataclass
class SendResult:
    message_id: str
    provider: str


class EmailProvider(Protocol):
    def send(self, message: OutboundMessage) -> SendResult: ...


# --------------------------------------------------------------- factories
def get_research_provider() -> ResearchProvider:
    from jobapp.providers.fakes import FakeResearchProvider

    # Real web-research adapter arrives post-slice; fake is explicit + honest.
    return FakeResearchProvider()


def get_ai_provider() -> AIProvider:
    from jobapp.providers.fakes import FakeAIProvider

    settings = get_settings()
    if not settings.anthropic_api_key:
        return FakeAIProvider()
    raise NotImplementedError(
        "Anthropic adapter lands in the next milestone; unset ANTHROPIC_API_KEY "
        "to use the deterministic fake."
    )


def get_email_provider() -> EmailProvider:
    from jobapp.providers.fakes import FakeEmailProvider
    from jobapp.providers.smtp import SmtpEmailProvider, smtp_configured

    if smtp_configured():
        return SmtpEmailProvider()
    return FakeEmailProvider.shared()
