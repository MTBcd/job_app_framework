# =========================
# file: src/jobapp/retry_logic.py
# =========================
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from .history import SendHistoryStore, build_person_key


SUCCESS_STATUSES = {
    "dry_run",
    "sent",
    "delivered",
    "replied",
}

BOUNCE_OR_FAILURE_STATUSES = {
    "hard_bounce",
    "soft_bounce",
    "failed_hard_bounce",
    "failed_soft_bounce",
    "failed_send",
}

TERMINAL_STATUSES = SUCCESS_STATUSES | BOUNCE_OR_FAILURE_STATUSES


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def load_candidates(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = row.get("email_candidates_json", "")
    if not raw:
        return []

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []

    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def sort_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        candidates,
        key=lambda item: (_safe_float(item.get("confidence")), item.get("email", "")),
        reverse=True,
    )


def _soft_bounce_count(attempts: List[Dict[str, str]], email_attempted: str) -> int:
    needle = str(email_attempted or "").strip().lower()
    return sum(
        1
        for attempt in attempts
        if attempt.get("email_attempted", "").strip().lower() == needle
        and attempt.get("status") in {"soft_bounce", "failed_soft_bounce"}
    )


def _has_success(attempts: List[Dict[str, str]]) -> bool:
    return any(attempt.get("status") in SUCCESS_STATUSES for attempt in attempts)


def _has_failure(attempts: List[Dict[str, str]]) -> bool:
    return any(attempt.get("status") in BOUNCE_OR_FAILURE_STATUSES for attempt in attempts)


def _tried_emails(attempts: List[Dict[str, str]]) -> set[str]:
    return {
        attempt.get("email_attempted", "").strip().lower()
        for attempt in attempts
        if attempt.get("email_attempted", "").strip()
        and attempt.get("status") in TERMINAL_STATUSES
    }


def choose_next_candidate(
    row: Dict[str, Any],
    history_store: SendHistoryStore,
    *,
    max_attempts_per_person: int = 3,
    max_retries_same_soft_bounce: int = 2,
    require_existing_failure: bool = False,
) -> Optional[Dict[str, Any]]:
    person_key = build_person_key(row)
    attempts = history_store.attempts_for_person(person_key)

    if _has_success(attempts):
        return None

    if require_existing_failure and not _has_failure(attempts):
        return None

    if len(attempts) >= max_attempts_per_person:
        return None

    tried_emails = _tried_emails(attempts)

    candidates = sort_candidates(load_candidates(row))
    if not candidates and row.get("email_selected"):
        candidates = [
            {
                "email": row.get("email_selected", ""),
                "pattern": row.get("email_pattern", ""),
                "confidence": row.get("email_confidence", ""),
                "reasoning": row.get("email_reasoning", ""),
            }
        ]

    for candidate in candidates:
        email_value = str(candidate.get("email", "")).strip().lower()
        if not email_value:
            continue
        if email_value in tried_emails:
            continue
        if _soft_bounce_count(attempts, email_value) >= max_retries_same_soft_bounce:
            continue
        return candidate

    return None


def should_skip_person(
    row: Dict[str, Any],
    history_store: SendHistoryStore,
    *,
    max_attempts_per_person: int = 3,
) -> Tuple[bool, str]:
    person_key = build_person_key(row)
    attempts = history_store.attempts_for_person(person_key)

    if _has_success(attempts):
        return True, "skipped_already_sent"

    if len(attempts) >= max_attempts_per_person:
        return True, "skipped_retry_exhausted"

    selected_email = str(row.get("email_selected", "")).strip().lower()
    if not selected_email:
        return False, ""

    same_email_attempts = history_store.attempts_for_person_email(person_key, selected_email)
    same_email_statuses = {
        attempt.get("status", "")
        for attempt in same_email_attempts
        if attempt.get("status", "")
    }

    if same_email_statuses & TERMINAL_STATUSES:
        return True, "skipped_duplicate_candidate"

    return False, ""


def prepare_retry_row(
    row: Dict[str, Any],
    history_store: SendHistoryStore,
    *,
    max_attempts_per_person: int = 3,
    max_retries_same_soft_bounce: int = 2,
) -> Optional[Dict[str, Any]]:
    next_candidate = choose_next_candidate(
        row,
        history_store,
        max_attempts_per_person=max_attempts_per_person,
        max_retries_same_soft_bounce=max_retries_same_soft_bounce,
        require_existing_failure=True,
    )

    if not next_candidate:
        return None

    person_key = build_person_key(row)
    attempts = history_store.attempts_for_person(person_key)

    retry_row = dict(row)
    retry_row["email_selected"] = next_candidate.get("email", "")
    retry_row["email_pattern"] = next_candidate.get("pattern", "")
    retry_row["email_confidence"] = next_candidate.get("confidence", "")

    reasoning = next_candidate.get("reasoning", "")
    retry_row["email_reasoning"] = (
        "; ".join(str(item) for item in reasoning)
        if isinstance(reasoning, list)
        else reasoning
    )

    failed_emails = [
        attempt.get("email_attempted", "")
        for attempt in attempts
        if attempt.get("status") in BOUNCE_OR_FAILURE_STATUSES
    ]

    retry_row["send_status"] = "retry_ready"
    retry_row["retry_reason"] = "previous_attempt_failed_or_bounced"
    retry_row["previous_failed_emails"] = "; ".join(email for email in failed_emails if email)
    retry_row["previous_attempt_count"] = len(attempts)

    return retry_row