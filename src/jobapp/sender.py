# =========================
# file: src/jobapp/sender.py
# =========================
from __future__ import annotations

import mimetypes
import os
import re
import smtplib
import time
import uuid
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from .history import HistoryRecord, SendHistoryStore, build_person_key, utc_now_iso
from .learning import LearningEvent, LearningStore
from .retry_logic import prepare_retry_row, should_skip_person


EMAIL_RE = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)

HARD_BOUNCE_PATTERNS = [
    r"\b550\b",
    r"\b551\b",
    r"\b553\b",
    r"user unknown",
    r"unknown user",
    r"mailbox unavailable",
    r"invalid recipient",
    r"recipient address rejected",
    r"no such user",
    r"mailbox not found",
    r"address rejected",
    r"not our customer",
]

SOFT_BOUNCE_PATTERNS = [
    r"\b421\b",
    r"\b450\b",
    r"\b451\b",
    r"\b452\b",
    r"\b4\.\d\.\d\b",
    r"temporar",
    r"try again later",
    r"rate limit",
    r"greylist",
    r"timed out",
]


def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _split_csv(value: Any) -> List[str]:
    if not value:
        return []
    return [item.strip().lower() for item in str(value).split(",") if item.strip()]


@dataclass
class SendSettings:
    dry_run: bool = True
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_use_tls: bool = True
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_from_name: str = ""
    reply_to: str = ""
    attachment_path: str = ""
    send_rate_seconds: float = 3.0
    max_emails_per_run: int = 20
    allowed_recipient_domains: str = ""
    blocked_recipient_domains: str = ""
    send_history_path: str = "logs/send_history.csv"
    learning_feedback_path: str = "logs/learning_feedback.csv"
    max_attempts_per_person: int = 3
    max_retries_same_soft_bounce: int = 2

    @classmethod
    def from_env(cls) -> "SendSettings":
        return cls(
            dry_run=_to_bool(os.getenv("DRY_RUN", "true"), True),
            smtp_host=os.getenv("SMTP_HOST", "smtp.gmail.com"),
            smtp_port=int(os.getenv("SMTP_PORT", "587")),
            smtp_use_tls=_to_bool(os.getenv("SMTP_USE_TLS", "true"), True),
            smtp_username=os.getenv("SMTP_USERNAME", ""),
            smtp_password=os.getenv("SMTP_PASSWORD", ""),
            smtp_from_email=os.getenv("SMTP_FROM_EMAIL", ""),
            smtp_from_name=os.getenv("SMTP_FROM_NAME", ""),
            reply_to=os.getenv("REPLY_TO", ""),
            attachment_path=os.getenv("ATTACHMENT_PATH", ""),
            send_rate_seconds=float(os.getenv("SEND_RATE_SECONDS", "3")),
            max_emails_per_run=int(os.getenv("MAX_EMAILS_PER_RUN", "20")),
            allowed_recipient_domains=os.getenv("ALLOWED_RECIPIENT_DOMAINS", ""),
            blocked_recipient_domains=os.getenv("BLOCKED_RECIPIENT_DOMAINS", ""),
            send_history_path=os.getenv("SEND_HISTORY_PATH", "logs/send_history.csv"),
            learning_feedback_path=os.getenv("LEARNING_FEEDBACK_PATH", "logs/learning_feedback.csv"),
            max_attempts_per_person=int(os.getenv("MAX_ATTEMPTS_PER_PERSON", "3")),
            max_retries_same_soft_bounce=int(os.getenv("MAX_RETRIES_SAME_SOFT_BOUNCE", "2")),
        )


def is_valid_email(email_value: str) -> bool:
    return bool(email_value and EMAIL_RE.match(email_value.strip()))


def recipient_domain(email_value: str) -> str:
    return email_value.split("@", 1)[1].lower().strip() if "@" in email_value else ""


def is_allowed_recipient(email_value: str, settings: SendSettings) -> tuple[bool, str]:
    if not is_valid_email(email_value):
        return False, "invalid_email"

    domain = recipient_domain(email_value)
    allowed = _split_csv(settings.allowed_recipient_domains)
    blocked = _split_csv(settings.blocked_recipient_domains)

    if allowed and domain not in allowed:
        return False, "domain_not_allowed"
    if domain in blocked:
        return False, "blocked_consumer_domain"
    return True, ""


def _was_email_already_attempted(history_store: SendHistoryStore, email_value: str) -> bool:
    email_value = email_value.strip().lower()
    if not email_value:
        return False
    attempts = history_store.attempts_for_email(email_value)
    return any(
        attempt.get("status") in {"sent", "delivered", "replied", "dry_run"}
        for attempt in attempts
    )


def _attach_file(msg: EmailMessage, attachment_path: str) -> None:
    if not attachment_path.strip():
        return

    attachment = Path(attachment_path).expanduser()
    if not attachment.exists():
        raise FileNotFoundError(f"Attachment not found: {attachment}")

    content_type, _ = mimetypes.guess_type(str(attachment))
    if content_type:
        maintype, subtype = content_type.split("/", 1)
    else:
        maintype, subtype = "application", "octet-stream"

    with attachment.open("rb") as handle:
        msg.add_attachment(
            handle.read(),
            maintype=maintype,
            subtype=subtype,
            filename=attachment.name,
        )


def build_message(row: Dict[str, Any], settings: SendSettings) -> EmailMessage:
    msg = EmailMessage()

    from_header = (
        f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
        if settings.smtp_from_name
        else settings.smtp_from_email
    )

    msg["From"] = from_header
    msg["To"] = str(row.get("email_selected", "")).strip()
    msg["Subject"] = str(row.get("draft_subject", "")).strip()

    if settings.reply_to:
        msg["Reply-To"] = settings.reply_to

    msg.set_content(str(row.get("draft_body", "")).strip())
    _attach_file(msg, settings.attachment_path)
    return msg


def send_message(msg: EmailMessage, settings: SendSettings) -> str:
    message_id = f"<{uuid.uuid4()}@local.jobapp>"
    msg["Message-ID"] = message_id

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        if settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(msg)

    return message_id


def classify_send_failure(exc: Exception) -> tuple[str, str]:
    message = str(exc).strip()
    lowered = message.lower()

    if isinstance(exc, FileNotFoundError):
        return "failed_attachment_missing", message

    for pattern in HARD_BOUNCE_PATTERNS:
        if re.search(pattern, lowered):
            return "failed_hard_bounce", message

    for pattern in SOFT_BOUNCE_PATTERNS:
        if re.search(pattern, lowered):
            return "failed_soft_bounce", message

    return "failed_send", message


def _history_record_from_row(
    row: Dict[str, Any],
    *,
    status: str,
    message_id: str = "",
    failure_reason: str = "",
    history_store: SendHistoryStore,
) -> HistoryRecord:
    person_key = build_person_key(row)

    return HistoryRecord(
        person_key=person_key,
        full_name=str(row.get("full_name", "")),
        company_name=str(row.get("company_name", "")),
        company_normalized=str(row.get("company_normalized", "")),
        domain=str(row.get("domain", "") or row.get("company_domain", "")),
        email_attempted=str(row.get("email_selected", "")),
        email_pattern=str(row.get("email_pattern", "")),
        attempt_number=history_store.next_attempt_number(person_key),
        status=status,
        failure_reason=failure_reason,
        message_id=message_id,
        sent_at_utc=utc_now_iso(),
        source_file=str(row.get("source_file", "")),
        source_row_number=str(row.get("source_row_number", "")),
        email_confidence=str(row.get("email_confidence", "")),
        email_reasoning=str(row.get("email_reasoning", "")),
        email_candidates_json=str(row.get("email_candidates_json", "")),
    )


def _learning_event_from_row(
    row: Dict[str, Any],
    *,
    event_type: str,
    message_id: str = "",
    source: str = "sender",
) -> LearningEvent:
    return LearningEvent(
        event_type=event_type,
        company_normalized=str(row.get("company_normalized", "")),
        domain=str(row.get("domain", "") or row.get("company_domain", "")),
        email_pattern=str(row.get("email_pattern", "")),
        email=str(row.get("email_selected", "")),
        message_id=message_id,
        source=source,
    )


# def send_dataframe(
#     df: pd.DataFrame,
#     settings: Optional[SendSettings] = None,
# ) -> pd.DataFrame:
#     settings = settings or SendSettings.from_env()
#     history_store = SendHistoryStore(settings.send_history_path)
#     learning_store = LearningStore(settings.learning_feedback_path)

#     sent_count = 0
#     output_rows: List[Dict[str, Any]] = []

#     for _, source_row in df.iterrows():
#         row = source_row.to_dict()
#         if bool(row.get("needs_manual_review", False)):
#             row["send_status"] = "skipped_manual_review"
#             row["send_error"] = str(row.get("manual_review_reason", "needs_manual_review"))
#             output_rows.append(row)
#             continue
#         recipient = str(row.get("email_selected", "")).strip().lower()

#         skip, skip_status = should_skip_person(
#             row,
#             history_store,
#             max_attempts_per_person=settings.max_attempts_per_person,
#         )
#         if skip:
#             row["send_status"] = skip_status
#             output_rows.append(row)
#             continue

#         if _was_email_already_attempted(history_store, recipient):
#             row["send_status"] = "skipped_duplicate_email"
#             row["send_error"] = "email_already_attempted"
#             output_rows.append(row)
#             continue

#         allowed, reason = is_allowed_recipient(recipient, settings)
#         if not allowed:
#             row["send_status"] = "skipped"
#             row["send_error"] = reason
#             output_rows.append(row)
#             continue

#         if sent_count >= settings.max_emails_per_run:
#             row["send_status"] = "skipped_run_limit"
#             output_rows.append(row)
#             continue

#         if settings.dry_run:
#             row["send_status"] = "dry_run"
#             history_store.append(
#                 _history_record_from_row(
#                     row,
#                     status="dry_run",
#                     history_store=history_store,
#                 )
#             )
#             output_rows.append(row)
#             sent_count += 1
#             continue

#         try:
#             message = build_message(row, settings)
#             message_id = send_message(message, settings)

#             row["send_status"] = "sent"
#             row["message_id"] = message_id

#             history_store.append(
#                 _history_record_from_row(
#                     row,
#                     status="sent",
#                     message_id=message_id,
#                     history_store=history_store,
#                 )
#             )
#             learning_store.append(
#                 _learning_event_from_row(
#                     row,
#                     event_type="sent",
#                     message_id=message_id,
#                     source="sender",
#                 )
#             )

#             output_rows.append(row)
#             sent_count += 1
#             time.sleep(settings.send_rate_seconds)

#         except Exception as exc:
#             failure_status, failure_reason = classify_send_failure(exc)
#             row["send_status"] = failure_status
#             row["send_error"] = failure_reason

#             history_store.append(
#                 _history_record_from_row(
#                     row,
#                     status=failure_status,
#                     failure_reason=failure_reason,
#                     history_store=history_store,
#                 )
#             )

#             event_type = (
#                 "hard_bounce"
#                 if failure_status == "failed_hard_bounce"
#                 else "soft_bounce"
#                 if failure_status == "failed_soft_bounce"
#                 else "failed_send"
#             )
#             learning_store.append(
#                 _learning_event_from_row(
#                     row,
#                     event_type=event_type,
#                     source="sender",
#                 )
#             )
#             output_rows.append(row)

#     return pd.DataFrame(output_rows)

def send_dataframe(
    df: pd.DataFrame,
    settings: Optional[SendSettings] = None,
) -> pd.DataFrame:
    settings = settings or SendSettings.from_env()
    history_store = SendHistoryStore(settings.send_history_path)
    learning_store = LearningStore(settings.learning_feedback_path)

    sent_count = 0
    output_rows: List[Dict[str, Any]] = []

    hard_block_reasons = {
        "no_email_candidates",
        "missing_company",
        "missing_last_name",
        "first_name_initial_only",
        "invalid_email",
    }

    for _, source_row in df.iterrows():
        row = source_row.to_dict()
        recipient = str(row.get("email_selected", "")).strip().lower()

        manual_review_reason = str(row.get("manual_review_reason", "")).lower()
        should_hard_block = any(
            reason in manual_review_reason
            for reason in hard_block_reasons
        )

        if bool(row.get("needs_manual_review", False)) and should_hard_block:
            row["send_status"] = "skipped_manual_review"
            row["send_error"] = str(row.get("manual_review_reason", "needs_manual_review"))
            output_rows.append(row)
            continue

        skip, skip_status = should_skip_person(
            row,
            history_store,
            max_attempts_per_person=settings.max_attempts_per_person,
        )
        if skip:
            row["send_status"] = skip_status
            output_rows.append(row)
            continue

        if _was_email_already_attempted(history_store, recipient):
            row["send_status"] = "skipped_duplicate_email"
            row["send_error"] = "email_already_attempted"
            output_rows.append(row)
            continue

        allowed, reason = is_allowed_recipient(recipient, settings)
        if not allowed:
            row["send_status"] = "skipped"
            row["send_error"] = reason
            output_rows.append(row)
            continue

        if sent_count >= settings.max_emails_per_run:
            row["send_status"] = "skipped_run_limit"
            output_rows.append(row)
            continue

        if settings.dry_run:
            row["send_status"] = "dry_run"
            history_store.append(
                _history_record_from_row(
                    row,
                    status="dry_run",
                    history_store=history_store,
                )
            )
            output_rows.append(row)
            sent_count += 1
            continue

        try:
            message = build_message(row, settings)
            message_id = send_message(message, settings)

            row["send_status"] = "sent"
            row["message_id"] = message_id

            history_store.append(
                _history_record_from_row(
                    row,
                    status="sent",
                    message_id=message_id,
                    history_store=history_store,
                )
            )
            learning_store.append(
                _learning_event_from_row(
                    row,
                    event_type="sent",
                    message_id=message_id,
                    source="sender",
                )
            )

            output_rows.append(row)
            sent_count += 1
            time.sleep(settings.send_rate_seconds)

        except Exception as exc:
            failure_status, failure_reason = classify_send_failure(exc)
            row["send_status"] = failure_status
            row["send_error"] = failure_reason

            history_store.append(
                _history_record_from_row(
                    row,
                    status=failure_status,
                    failure_reason=failure_reason,
                    history_store=history_store,
                )
            )

            event_type = (
                "hard_bounce"
                if failure_status == "failed_hard_bounce"
                else "soft_bounce"
                if failure_status == "failed_soft_bounce"
                else "failed_send"
            )
            learning_store.append(
                _learning_event_from_row(
                    row,
                    event_type=event_type,
                    source="sender",
                )
            )
            output_rows.append(row)

    return pd.DataFrame(output_rows)


def build_retry_queue(
    source_df: pd.DataFrame,
    settings: Optional[SendSettings] = None,
) -> pd.DataFrame:
    settings = settings or SendSettings.from_env()
    history_store = SendHistoryStore(settings.send_history_path)

    retry_rows: List[Dict[str, Any]] = []
    for _, source_row in source_df.iterrows():
        retry_row = prepare_retry_row(
            source_row.to_dict(),
            history_store,
            max_attempts_per_person=settings.max_attempts_per_person,
            max_retries_same_soft_bounce=settings.max_retries_same_soft_bounce,
        )
        if retry_row:
            retry_rows.append(retry_row)

    return pd.DataFrame(retry_rows)