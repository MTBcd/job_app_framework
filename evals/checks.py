"""Automatic quality checks for generated application emails.

Contract checks apply to every provider (fake included). Length checks are
strict only for real providers — the deterministic fake is intentionally
minimal. Grounding of numbers: any number in the email must literally appear
in the inputs (cheap, effective hallucination tripwire)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from jobapp.providers.prompts import FORBIDDEN_PHRASES

GENERIC_SUBJECTS = {
    "job application", "application", "opportunity", "hello", "hi",
    "introduction", "inquiry", "resume", "cv", "open position",
}

CTA_MARKERS = ("call", "chat", "meet", "connect", "conversation", "speak",
               "talk", "reply", "happy to share", "?")

SALESY_MARKERS = ("!", "exciting", "amazing", "incredible", "revolutionary",
                  "rockstar", "game-chang", "cutting-edge", "world-class")


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


def _words(text: str) -> int:
    return len(text.split())


def run_checks(
    scenario: dict, subject: str, body: str, *, strict_length: bool = True
) -> list[CheckResult]:
    results: list[CheckResult] = []
    body_lower = body.lower()
    subject_lower = subject.strip().lower()
    inputs_serialized = json.dumps(scenario, ensure_ascii=False).lower()

    word_count = _words(body)
    if strict_length:
        results.append(CheckResult(
            "word_count_120_180", 120 <= word_count <= 180, f"{word_count} words"))
    else:
        results.append(CheckResult(
            "not_too_long", word_count <= 220, f"{word_count} words"))

    hits = [p for p in FORBIDDEN_PHRASES if p in body_lower or p in subject_lower]
    results.append(CheckResult(
        "no_forbidden_phrases", not hits, "; ".join(hits)))

    prohibited = [c for c in scenario["prohibited_claims"] if c.lower() in body_lower]
    results.append(CheckResult(
        "no_prohibited_claims", not prohibited, "; ".join(prohibited)))

    missing = [t for t in scenario["required_terms"] if t.lower() not in body_lower]
    results.append(CheckResult(
        "required_terms_present", not missing, f"missing: {missing}" if missing else ""))

    # The exact official company name must appear in the body — pronouns or
    # shortened possessives don't count as naming the company (p2 rule).
    company = scenario["opportunity"]["company"]
    results.append(CheckResult(
        "company_name_in_body", company.lower() in body_lower, company))

    results.append(CheckResult(
        "subject_not_generic",
        bool(subject.strip())
        and subject_lower not in GENERIC_SUBJECTS
        and len(subject) <= 90,
        subject))

    salesy = [m for m in SALESY_MARKERS if m in subject_lower]
    results.append(CheckResult(
        "subject_not_salesy", not salesy, "; ".join(salesy)))

    results.append(CheckResult(
        "cta_present", any(marker in body_lower for marker in CTA_MARKERS)))

    # Numbers grounding: every number in the email must appear in the inputs.
    ungrounded = [n for n in re.findall(r"\d[\d,.]*", body)
                  if n.strip(",.") not in inputs_serialized]
    results.append(CheckResult(
        "numbers_grounded", not ungrounded, f"invented: {ungrounded}" if ungrounded else ""))

    results.append(CheckResult("no_bullet_points",
                               not re.search(r"^\s*[-•*]\s", body, re.MULTILINE)))

    return results


def score(results: list[CheckResult]) -> tuple[int, int]:
    return sum(1 for r in results if r.passed), len(results)
