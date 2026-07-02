# =========================
# file: src/jobapp/bounce_parser.py
# =========================
from __future__ import annotations

import email
import imaplib
import os
import re
from dataclasses import dataclass
from email.message import Message
from typing import List, Optional

from .history import SendHistoryStore
from .learning import LearningEvent, LearningStore

import csv
from datetime import datetime, timezone
from pathlib import Path

EMAIL_RE = re.compile(
    r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}",
    re.IGNORECASE,
)

BOUNCE_SENDER_PATTERNS = [
    "mailer-daemon",
    "mail delivery subsystem",
    "postmaster",
    "delivery subsystem",
    "googlemail.com",
]

BOUNCE_SUBJECT_PATTERNS = [
    "delivery status notification",
    "failure",
    "undeliverable",
    "undelivered",
    "returned mail",
    "mail delivery failed",
    "message not delivered",
    "adresse introuvable",
    "échec de la remise",
]

HARD_BOUNCE_PATTERNS = [
    r"user unknown",
    r"unknown user",
    r"no such user",
    r"recipient address rejected",
    r"recipient rejected",
    r"mailbox unavailable",
    r"invalid recipient",
    r"recipient not found",
    r"mailbox not found",
    r"address does not exist",
    r"address not found",
    r"adresse introuvable",
    r"n'existe pas",
    r"ne peut pas recevoir de messages",
    r"couldn't be found",
    r"could not be found",
    r"does not exist",
    r"550 5\.1\.1",
    r"550 5\.1\.0",
    r"550 5\.2\.1",
    r"\b550\b",
    r"\b551\b",
    r"\b553\b",
]

SOFT_BOUNCE_PATTERNS = [
    r"mailbox full",
    r"quota exceeded",
    r"try again later",
    r"temporar",
    r"rate limit",
    r"server busy",
    r"resources temporarily unavailable",
    r"greylist",
    r"timed out",
    r"\b421\b",
    r"\b450\b",
    r"\b451\b",
    r"\b452\b",
    r"\b4\.\d\.\d\b",
]

RECIPIENT_PATTERNS = [
    r"Final-Recipient:\s*rfc822;\s*([^\s;>]+@[^\s;>]+)",
    r"Original-Recipient:\s*rfc822;\s*([^\s;>]+@[^\s;>]+)",
    r"X-Failed-Recipients:\s*([^\s;>]+@[^\s;>]+)",
    r"Your message wasn't delivered to\s+([^\s;>]+@[^\s;>]+)",
    r"Votre message n'est pas parvenu à\s+([^\s;>,]+@[^\s;>,]+)",
    r"n'est pas parvenu à\s+([^\s;>,]+@[^\s;>,]+)",
    r"message.*?to\s+([^\s;>]+@[^\s;>]+)",
    r"for <([^>]+@[A-Z0-9._%+\-]+\.[A-Z]{2,})>",
    r"recipient[:\s]+([^\s;>]+@[^\s;>]+)",
    r"to[:\s]+([^\s;>]+@[^\s;>]+)",
]


@dataclass
class BounceResult:
    recipient_email: str
    bounce_type: str
    reason: str
    subject: str = ""
    message_id: str = ""
    sender: str = ""


def _clean_email(value: str) -> str:
    return value.strip().lower().strip(".,;:<>[]()\"'")


def _header_value(msg: Message, name: str) -> str:
    value = msg.get(name, "")
    if not value:
        return ""
    try:
        decoded = email.header.decode_header(value)
        parts: list[str] = []
        for chunk, charset in decoded:
            if isinstance(chunk, bytes):
                parts.append(chunk.decode(charset or "utf-8", errors="replace"))
            else:
                parts.append(chunk)
        return "".join(parts)
    except Exception:
        return str(value)

def _imap_date_from_history(history_path: str) -> str:
    path = Path(history_path)
    if not path.exists():
        return datetime.now(timezone.utc).strftime("%d-%b-%Y")

    dates: list[datetime] = []

    with path.open("r", newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            raw = row.get("sent_at_utc", "")
            if not raw:
                continue
            try:
                dates.append(datetime.fromisoformat(raw.replace("Z", "+00:00")))
            except ValueError:
                continue

    if not dates:
        return datetime.now(timezone.utc).strftime("%d-%b-%Y")

    earliest = min(dates)
    return earliest.strftime("%d-%b-%Y")

def is_likely_bounce(msg: Message, text: str = "") -> bool:
    sender = _header_value(msg, "From").lower()
    subject = _header_value(msg, "Subject").lower()
    combined = f"{sender}\n{subject}\n{text}".lower()

    if any(pattern in sender for pattern in BOUNCE_SENDER_PATTERNS):
        return True

    if any(pattern in subject for pattern in BOUNCE_SUBJECT_PATTERNS):
        return True

    if "delivery-status" in combined or "final-recipient" in combined:
        return True

    if "adresse introuvable" in combined:
        return True

    return False


def classify_bounce_reason(text: str) -> str:
    lowered = text.lower()

    for pattern in HARD_BOUNCE_PATTERNS:
        if re.search(pattern, lowered):
            return "hard_bounce"

    for pattern in SOFT_BOUNCE_PATTERNS:
        if re.search(pattern, lowered):
            return "soft_bounce"

    return "unknown_bounce"


def extract_failed_recipient(text: str, history_store: SendHistoryStore | None = None) -> str:
    for pattern in RECIPIENT_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            candidate = _clean_email(match.group(1))
            if EMAIL_RE.fullmatch(candidate):
                return candidate

    emails = [_clean_email(match) for match in EMAIL_RE.findall(text)]
    emails = [
        item
        for item in emails
        if not item.endswith("@googlemail.com")
        and not item.endswith("@gmail.com")
        and "mailer-daemon" not in item
        and "postmaster" not in item
    ]

    if history_store:
        attempted = {
            row.get("email_attempted", "").strip().lower()
            for row in history_store.load()
            if row.get("email_attempted", "").strip()
        }
        for item in emails:
            if item in attempted:
                return item

    return emails[0] if emails else ""


def message_to_text(msg: Message) -> str:
    parts: list[str] = []

    for header in ["From", "To", "Subject", "X-Failed-Recipients"]:
        value = _header_value(msg, header)
        if value:
            parts.append(f"{header}: {value}")

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()

            if content_type == "message/rfc822":
                payload = part.get_payload()
                if isinstance(payload, list):
                    for nested in payload:
                        if isinstance(nested, Message):
                            parts.append(message_to_text(nested))
                continue

            if content_type in {
                "text/plain",
                "text/html",
                "message/delivery-status",
            }:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        parts.append(payload.decode(charset, errors="replace"))
                    except LookupError:
                        parts.append(payload.decode("utf-8", errors="replace"))
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            parts.append(payload.decode(charset, errors="replace"))

    return "\n".join(parts)


def parse_bounce_message(
    msg: Message,
    history_store: SendHistoryStore | None = None,
) -> Optional[BounceResult]:
    subject = _header_value(msg, "Subject")
    message_id = _header_value(msg, "Message-ID")
    sender = _header_value(msg, "From")
    text = message_to_text(msg)
    combined = f"{sender}\n{subject}\n{text}"

    if not is_likely_bounce(msg, text):
        return None

    recipient_email = extract_failed_recipient(combined, history_store=history_store)
    if not recipient_email:
        return None

    return BounceResult(
        recipient_email=recipient_email,
        bounce_type=classify_bounce_reason(combined),
        reason=combined[:1500].replace("\x00", " ").strip(),
        subject=subject,
        message_id=message_id,
        sender=sender,
    )


def fetch_bounces_via_imap(
    *,
    imap_host: str,
    imap_username: str,
    imap_password: str,
    mailbox: str = "INBOX",
    search_criteria: str = "AUTO",
    history_store: SendHistoryStore | None = None,
) -> List[BounceResult]:
    results: list[BounceResult] = []
    seen: set[tuple[str, str, str]] = set()

    client = imaplib.IMAP4_SSL(imap_host)
    client.login(imap_username, imap_password)

    try:
        client.select(mailbox)
        status, data = client.search(None, search_criteria)
        if status != "OK":
            return results

        for raw_id in data[0].split():
            status, message_data = client.fetch(raw_id, "(RFC822)")
            if status != "OK" or not message_data or not message_data[0]:
                continue

            try:
                raw_email = message_data[0][1]
                msg = email.message_from_bytes(raw_email)
            except Exception:
                continue

            parsed = parse_bounce_message(msg, history_store=history_store)
            if not parsed:
                continue

            key = (parsed.recipient_email, parsed.bounce_type, parsed.subject)
            if key in seen:
                continue
            seen.add(key)
            results.append(parsed)

    finally:
        try:
            client.close()
        except Exception:
            pass
        client.logout()

    return results


def sync_bounce_feedback(
    *,
    history_path: str = "logs/send_history.csv",
    learning_path: str = "logs/learning_feedback.csv",
    imap_host: Optional[str] = None,
    imap_username: Optional[str] = None,
    imap_password: Optional[str] = None,
    mailbox: str = "INBOX",
    search_criteria: str = "AUTO",
) -> List[BounceResult]:
    imap_host = imap_host or os.getenv("IMAP_HOST", "")
    imap_username = imap_username or os.getenv("IMAP_USERNAME", "")
    imap_password = imap_password or os.getenv("IMAP_PASSWORD", "")

    if not (imap_host and imap_username and imap_password):
        return []

    history_store = SendHistoryStore(history_path)
    learning_store = LearningStore(learning_path)
    applied: list[BounceResult] = []

    since_date = _imap_date_from_history(history_path)

    if search_criteria == "AUTO":
        search_criteria = f'(SINCE "{since_date}")'

    bounce_results = fetch_bounces_via_imap(
        imap_host=imap_host,
        imap_username=imap_username,
        imap_password=imap_password,
        mailbox=mailbox,
        search_criteria=search_criteria,
        history_store=history_store,
    )

    for result in bounce_results:
        matching_rows = history_store.attempts_for_email(result.recipient_email)
        if not matching_rows:
            continue

        latest = matching_rows[-1]

        if result.bounce_type == "hard_bounce":
            new_status = "failed_hard_bounce"
            event_type = "hard_bounce"
        elif result.bounce_type == "soft_bounce":
            new_status = "failed_soft_bounce"
            event_type = "soft_bounce"
        else:
            new_status = "failed_send"
            event_type = "failed_send"

        history_store.update_status(
            email_attempted=result.recipient_email,
            new_status=new_status,
            failure_reason=result.reason[:500],
        )

        if not learning_store.has_message_event(latest.get("message_id", ""), event_type):
            learning_store.append(
                LearningEvent(
                    event_type=event_type,
                    company_normalized=latest.get("company_normalized", ""),
                    domain=latest.get("domain", ""),
                    email_pattern=latest.get("email_pattern", ""),
                    email=latest.get("email_attempted", ""),
                    message_id=latest.get("message_id", ""),
                    source="bounce_parser",
                )
            )

        applied.append(result)

    return applied