# =========================
# file: src/jobapp/email_inference.py
# =========================
from __future__ import annotations

import os
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

import pandas as pd

from .cleaning import (
    ascii_email_token,
    extract_domain,
    is_valid_email,
    normalize_email_localpart,
    normalize_whitespace,
    safe_json_dumps,
    slug_token,
)
from .learning import LearningStore
from .pattern_overrides import get_company_pattern


PATTERN_ORDER = [
    "first.last",
    "first",
    "firstlast",
    "flast",
    "f.last",
    "first_l",
    "first_last",
    "last.first",
    "last",
]

PATTERN_PRIORS = {
    "first.last": 0.66,
    "flast": 0.61,
    "firstlast": 0.57,
    "first": 0.53,
    "first_last": 0.50,
    "f.last": 0.49,
    "first_l": 0.45,
    "last.first": 0.38,
    "last": 0.35,
}

REVIEW_CONFIDENCE_THRESHOLD = 0.72
REVIEW_DELTA_THRESHOLD = 0.05


@dataclass
class EmailCandidate:
    email: str
    pattern: str
    confidence: float
    reasoning: list[str]


def _tokenize_first_name(first_name: str) -> dict[str, str]:
    first_ascii = ascii_email_token(first_name)
    if not first_ascii:
        return {"primary": "", "compact": "", "initial": "", "is_initial_only": False}

    raw_parts = [part for part in slug_token(first_name).split() if part]
    clean_parts = [ascii_email_token(part) for part in raw_parts if ascii_email_token(part)]
    compact = "".join(clean_parts) if clean_parts else first_ascii
    primary = clean_parts[0] if clean_parts else first_ascii
    return {
        "primary": primary,
        "compact": compact,
        "initial": primary[:1],
        "is_initial_only": len(compact) == 1,
    }


def _tokenize_last_name(last_name: str) -> dict[str, str]:
    last_ascii = ascii_email_token(last_name)
    if not last_ascii:
        return {"compact": "", "terminal": "", "initial": "", "has_particle": False}

    raw_parts = [part for part in slug_token(last_name).split() if part]
    clean_parts = [ascii_email_token(part) for part in raw_parts if ascii_email_token(part)]
    compact = "".join(clean_parts) if clean_parts else last_ascii
    terminal = clean_parts[-1] if clean_parts else last_ascii
    return {
        "compact": compact,
        "terminal": terminal,
        "initial": compact[:1],
        "has_particle": len(clean_parts) > 1 and compact != terminal,
    }


def _pattern_localparts(first_name: str, last_name: str) -> list[tuple[str, str, list[str]]]:
    first = _tokenize_first_name(first_name)
    last = _tokenize_last_name(last_name)
    if not first["primary"] or not last["compact"]:
        return []

    seen: set[tuple[str, str]] = set()
    localparts: list[tuple[str, str, list[str]]] = []

    first_variants = [first["primary"]]
    if first["compact"] and first["compact"] != first["primary"]:
        first_variants.append(first["compact"])

    last_variants = [last["compact"]]
    if last["terminal"] and last["terminal"] != last["compact"]:
        last_variants.append(last["terminal"])

    allowed_patterns = {"flast", "f.last"} if first["is_initial_only"] else set(PATTERN_ORDER)

    for pattern in PATTERN_ORDER:
        if pattern not in allowed_patterns:
            continue

        candidates: list[tuple[str, list[str]]] = []

        if pattern == "first.last":
            candidates = [
                (f"{f}.{l}", [f"first={f}", f"last={l}"])
                for f in first_variants
                for l in last_variants
            ]
        elif pattern == "first":
            candidates = [(f, [f"first={f}"]) for f in first_variants]
        elif pattern == "firstlast":
            candidates = [
                (f"{f}{l}", [f"first={f}", f"last={l}"])
                for f in first_variants
                for l in last_variants
            ]
        elif pattern == "flast":
            candidates = [
                (f"{first['initial']}{l}", [f"f={first['initial']}", f"last={l}"])
                for l in last_variants
            ]
        elif pattern == "f.last":
            candidates = [
                (f"{first['initial']}.{l}", [f"f={first['initial']}", f"last={l}"])
                for l in last_variants
            ]
        elif pattern == "first_l":
            candidates = [
                (f"{f}_{last['initial']}", [f"first={f}", f"l={last['initial']}"])
                for f in first_variants
            ]
        elif pattern == "first_last":
            candidates = [
                (f"{f}_{l}", [f"first={f}", f"last={l}"])
                for f in first_variants
                for l in last_variants
            ]
        elif pattern == "last.first":
            candidates = [
                (f"{l}.{f}", [f"last={l}", f"first={f}"])
                for f in first_variants
                for l in last_variants
            ]
        elif pattern == "last":
            candidates = [(l, [f"last={l}"]) for l in last_variants]

        for localpart, reasons in candidates:
            localpart = normalize_email_localpart(localpart)
            key = (pattern, localpart)
            if localpart and key not in seen:
                seen.add(key)
                localparts.append((pattern, localpart, reasons))

    return localparts


def generate_pattern_emails(first_name: str, last_name: str, domain: str) -> list[tuple[str, str, list[str]]]:
    domain = extract_domain(domain)
    if not domain:
        return []
    return [
        (pattern, f"{localpart}@{domain}", reasons)
        for pattern, localpart, reasons in _pattern_localparts(first_name, last_name)
    ]


def learn_domain_patterns(df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    counter_map: dict[str, Counter] = defaultdict(Counter)
    for _, row in df.iterrows():
        email_value = normalize_whitespace(row.get("email", ""))
        first_name = row.get("first_name", "")
        last_name = row.get("last_name", "")
        domain = extract_domain(email_value)

        if not (is_valid_email(email_value) and first_name and last_name and domain):
            continue

        for pattern, candidate, _ in generate_pattern_emails(first_name, last_name, domain):
            if candidate.lower() == email_value.lower():
                counter_map[domain][pattern] += 1
                break

    learned: dict[str, dict[str, Any]] = {}
    for domain, counter in counter_map.items():
        if counter:
            best_pattern, best_count = counter.most_common(1)[0]
            total = sum(counter.values())
            learned[domain] = {
                "pattern": best_pattern,
                "count": best_count,
                "total": total,
                "share": (best_count / total) if total else 0.0,
                "counts": dict(counter),
            }
    return learned


def score_candidates(
    first_name: str,
    last_name: str,
    domain: str,
    known_pattern_info: dict[str, Any] | None = None,
    is_initials_only: bool = False,
    company_normalized: str = "",
    domain_source: str = "",
    learning_store: LearningStore | None = None,
    verified_pattern_info: dict[str, Any] | None = None,
) -> list[EmailCandidate]:
    generated = generate_pattern_emails(first_name, last_name, domain)
    results: list[EmailCandidate] = []

    first = _tokenize_first_name(first_name)
    last = _tokenize_last_name(last_name)
    known_pattern = (known_pattern_info or {}).get("pattern")
    known_share = float((known_pattern_info or {}).get("share") or 0.0)
    known_count = int((known_pattern_info or {}).get("count") or 0)

    verified_pattern = ""
    verified_domain = ""
    verified_confidence = 0.0
    if verified_pattern_info:
        verified_pattern = normalize_whitespace(verified_pattern_info.get("email_pattern", "")).lower()
        verified_domain = extract_domain(verified_pattern_info.get("domain", ""))
        verified_confidence = float(verified_pattern_info.get("confidence", 0.95) or 0.95)

    for rank, (pattern, email_value, token_reasons) in enumerate(generated, start=1):
        score = PATTERN_PRIORS.get(pattern, 0.35)
        reasoning = [f"pattern={pattern}", f"domain={domain}", *token_reasons]

        if verified_domain and verified_domain == extract_domain(domain):
            score += 0.12
            reasoning.append("verified_company_domain")

        if verified_pattern and pattern == verified_pattern:
            score += min(0.30, verified_confidence * 0.30)
            reasoning.append("verified_company_email_pattern")

        if known_pattern and pattern == known_pattern:
            boost = 0.18 + min(0.12, known_share * 0.20) + min(0.06, known_count * 0.01)
            score += boost
            reasoning.append("matches_learned_domain_pattern")

        if pattern == "first.last":
            reasoning.append("north_american_default")
        elif pattern in {"flast", "firstlast", "first"}:
            reasoning.append("common_corporate_pattern")

        if is_initials_only or first["is_initial_only"]:
            if pattern in {"flast", "f.last"}:
                score += 0.12
                reasoning.append("first_name_initial_only_preference")
            else:
                score -= 0.18
                reasoning.append("avoids_inventing_full_first_name")

        if last["has_particle"]:
            if f"last={last['compact']}" in token_reasons:
                score += 0.04
                reasoning.append("compound_surname_supported")
            if f"last={last['terminal']}" in token_reasons:
                score += 0.02
                reasoning.append("terminal_surname_variant_supported")

        if len(last["compact"]) >= 12:
            score -= 0.02
            reasoning.append("long_last_name_penalty")

        if domain_source == "from_verified_pattern_file":
            score += 0.15
            reasoning.append("trusted_verified_pattern_file_domain")
        elif domain_source == "from_company_override":
            score += 0.08
            reasoning.append("trusted_domain_override")
        elif domain_source == "from_learning_feedback":
            score += 0.10
            reasoning.append("trusted_learned_domain")
        elif domain_source == "from_existing_domain_or_email":
            score += 0.12
            reasoning.append("trusted_existing_domain")
        elif domain_source == "heuristic_company_to_com":
            score -= 0.12
            reasoning.append("heuristic_domain_penalty")
        elif not domain_source:
            score -= 0.10
            reasoning.append("missing_domain_source")

        if learning_store:
            pattern_boost = learning_store.pattern_boost(company_normalized, domain, pattern)
            if pattern_boost:
                score += pattern_boost
                reasoning.append(f"feedback_pattern_boost={round(pattern_boost, 3)}")
            domain_boost = learning_store.domain_boost(company_normalized, domain)
            if domain_boost:
                score += domain_boost
                reasoning.append(f"feedback_domain_boost={round(domain_boost, 3)}")

        score -= (rank - 1) * 0.025

        if verified_pattern and pattern == verified_pattern and verified_domain == extract_domain(domain):
            score = max(score, min(0.97, verified_confidence))

        score = max(min(score, 0.99), 0.05)

        results.append(
            EmailCandidate(
                email=email_value,
                pattern=pattern,
                confidence=score,
                reasoning=reasoning,
            )
        )

    deduped: dict[str, EmailCandidate] = {}
    for item in sorted(results, key=lambda value: value.confidence, reverse=True):
        deduped.setdefault(item.email.lower(), item)

    return sorted(deduped.values(), key=lambda value: value.confidence, reverse=True)


def _review_flags(
    row: pd.Series,
    candidates: list[EmailCandidate],
    selected_score: float,
) -> tuple[bool, str]:
    reasons: list[str] = []

    domain_source = normalize_whitespace(row.get("domain_source", ""))
    verified_used = domain_source == "from_verified_pattern_file"

    if not normalize_whitespace(row.get("company_name", "")):
        reasons.append("missing_company")
    if not normalize_whitespace(row.get("last_name", "")):
        reasons.append("missing_last_name")
    if bool(row.get("is_initials_only", False)):
        reasons.append("first_name_initial_only")
    if normalize_whitespace(row.get("name_parse_warning", "")):
        reasons.append(normalize_whitespace(row.get("name_parse_warning", "")))
    if domain_source == "heuristic_company_to_com":
        reasons.append("heuristic_domain")
    if not candidates:
        reasons.append("no_email_candidates")
    if candidates and selected_score < REVIEW_CONFIDENCE_THRESHOLD and not verified_used:
        reasons.append("low_email_confidence")
    if len(candidates) >= 2:
        delta = candidates[0].confidence - candidates[1].confidence
        if delta < REVIEW_DELTA_THRESHOLD and not verified_used:
            reasons.append("top_candidates_too_close")

    deduped_reasons = []
    for reason in reasons:
        if reason and reason not in deduped_reasons:
            deduped_reasons.append(reason)

    return bool(deduped_reasons), "; ".join(deduped_reasons)


def apply_email_inference(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    learned_patterns = learn_domain_patterns(df)
    learning_store = LearningStore(os.getenv("LEARNING_FEEDBACK_PATH", "logs/learning_feedback.csv"))

    selected_emails: list[str] = []
    selected_patterns: list[str] = []
    selected_scores: list[float] = []
    selected_reasoning: list[str] = []
    candidates_json: list[str] = []
    needs_manual_review: list[bool] = []
    manual_review_reason: list[str] = []

    for _, row in df.iterrows():
        explicit_email = normalize_whitespace(row.get("email", ""))
        domain_source = normalize_whitespace(row.get("domain_source", ""))
        domain = (
            extract_domain(row.get("company_domain", ""))
            or extract_domain(row.get("domain", ""))
            or extract_domain(explicit_email)
        )
        first_name = row.get("first_name", "")
        last_name = row.get("last_name", "")
        is_initials_only = bool(row.get("is_initials_only", False))
        company_name = row.get("company_name", "")
        company_normalized = str(row.get("company_normalized", "")).strip().lower()

        verified_pattern = get_company_pattern(company_name, company_normalized)
        if verified_pattern and verified_pattern.get("domain"):
            domain = extract_domain(verified_pattern["domain"]) or domain
            domain_source = "from_verified_pattern_file"

        if is_valid_email(explicit_email):
            selected_emails.append(explicit_email)
            selected_patterns.append("provided")
            selected_scores.append(1.0)
            selected_reasoning.append("existing_valid_email")
            candidates_json.append(
                safe_json_dumps(
                    [
                        {
                            "email": explicit_email,
                            "pattern": "provided",
                            "confidence": 1.0,
                            "reasoning": ["existing_valid_email"],
                        }
                    ]
                )
            )
            review, review_reason = _review_flags(row, [], 1.0)
            needs_manual_review.append(review)
            manual_review_reason.append(review_reason)
            continue

        candidates = score_candidates(
            first_name,
            last_name,
            domain,
            known_pattern_info=learned_patterns.get(domain),
            is_initials_only=is_initials_only,
            company_normalized=company_normalized,
            domain_source=domain_source,
            learning_store=learning_store,
            verified_pattern_info=verified_pattern,
        )

        serialized = [
            {
                "email": item.email,
                "pattern": item.pattern,
                "confidence": round(item.confidence, 3),
                "reasoning": item.reasoning,
            }
            for item in candidates
        ]
        candidates_json.append(safe_json_dumps(serialized))

        if candidates:
            top = candidates[0]
            top_score = round(top.confidence, 3)
            selected_emails.append(top.email)
            selected_patterns.append(top.pattern)
            selected_scores.append(top_score)
            selected_reasoning.append("; ".join(top.reasoning))
            row_for_review = row.copy()
            row_for_review["domain_source"] = domain_source
            review, review_reason = _review_flags(row_for_review, candidates, top_score)
            needs_manual_review.append(review)
            manual_review_reason.append(review_reason)
        else:
            selected_emails.append("")
            selected_patterns.append("")
            selected_scores.append(0.0)
            selected_reasoning.append("could_not_infer_email")
            needs_manual_review.append(True)
            manual_review_reason.append("no_email_candidates")

    df["email_selected"] = selected_emails
    df["email_pattern"] = selected_patterns
    df["email_confidence"] = selected_scores
    df["email_reasoning"] = selected_reasoning
    df["email_candidates_json"] = candidates_json
    df["email_selected_is_valid"] = df["email_selected"].map(is_valid_email)
    df["needs_manual_review"] = needs_manual_review
    df["manual_review_reason"] = manual_review_reason
    return df