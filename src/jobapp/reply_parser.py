# =========================
# file: src/jobapp/reply_parser.py
# =========================
from __future__ import annotations

import csv
import email
import imaplib
import os
import re
from datetime import datetime, timezone
from email.message import Message
from pathlib import Path
from typing import Dict, List, Optional

from .history import SendHistoryStore
from .learning import LearningEvent, LearningStore


REPLY_SUBJECT_RE = re.compile(r"^(re|sv|aw)\s*:", re.IGNORECASE)
EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.IGNORECASE)

BOUNCE_SENDERS = {
    "mailer-daemon",
    "postmaster",
    "mail delivery subsystem",
}


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

    return min(dates).strftime("%d-%b-%Y")


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


def _extract_reference_ids(msg: Message) -> List[str]:
    references: List[str] = []
    for header_name in ("In-Reply-To", "References"):
        raw = _header_value(msg, header_name)
        if raw:
            references.extend(re.findall(r"<[^>]+>", raw))
    return list(dict.fromkeys(ref.strip() for ref in references if ref.strip()))


def _sender_email(msg: Message) -> str:
    match = EMAIL_RE.search(_header_value(msg, "From"))
    return match.group(0).lower() if match else ""


def _is_bounce_or_system_message(msg: Message) -> bool:
    sender = _header_value(msg, "From").lower()
    subject = _header_value(msg, "Subject").lower()
    if any(token in sender for token in BOUNCE_SENDERS):
        return True
    if "delivery status notification" in subject or "undeliverable" in subject:
        return True
    return False


def looks_like_reply(msg: Message) -> bool:
    if _is_bounce_or_system_message(msg):
        return False

    subject = _header_value(msg, "Subject")
    if REPLY_SUBJECT_RE.search(subject):
        return True

    if _header_value(msg, "In-Reply-To") or _header_value(msg, "References"):
        return True

    return False


def fetch_reply_messages(
    *,
    imap_host: str,
    imap_username: str,
    imap_password: str,
    mailbox: str = "INBOX",
    search_criteria: str = "ALL",
    max_messages: int = 300,
) -> List[Message]:
    client = imaplib.IMAP4_SSL(imap_host)
    client.login(imap_username, imap_password)
    messages: List[Message] = []

    try:
        client.select(mailbox)
        status, data = client.search(None, search_criteria)
        if status != "OK" or not data or not data[0]:
            return messages

        ids = data[0].split()
        ids = ids[-max_messages:]

        for raw_id in ids:
            try:
                status, payload = client.fetch(raw_id, "(RFC822)")
                if status != "OK" or not payload or not payload[0]:
                    continue

                msg = email.message_from_bytes(payload[0][1])
                if looks_like_reply(msg):
                    messages.append(msg)

            except Exception:
                continue

    finally:
        try:
            client.close()
        except Exception:
            pass
        try:
            client.logout()
        except Exception:
            pass

    return messages


def sync_reply_feedback(
    *,
    history_path: str = "logs/send_history.csv",
    learning_path: str = "logs/learning_feedback.csv",
    imap_host: Optional[str] = None,
    imap_username: Optional[str] = None,
    imap_password: Optional[str] = None,
    mailbox: str = "INBOX",
    search_criteria: str = "AUTO",
) -> List[Dict[str, str]]:
    imap_host = imap_host or os.getenv("IMAP_HOST", "")
    imap_username = imap_username or os.getenv("IMAP_USERNAME", "")
    imap_password = imap_password or os.getenv("IMAP_PASSWORD", "")
    if not (imap_host and imap_username and imap_password):
        return []

    if search_criteria == "AUTO":
        since_date = _imap_date_from_history(history_path)
        search_criteria = f'(SINCE "{since_date}")'

    history_store = SendHistoryStore(history_path)
    learning_store = LearningStore(learning_path)
    updated_rows: List[Dict[str, str]] = []

    for msg in fetch_reply_messages(
        imap_host=imap_host,
        imap_username=imap_username,
        imap_password=imap_password,
        mailbox=mailbox,
        search_criteria=search_criteria,
    ):
        sender_email = _sender_email(msg)
        matched_row = None

        for ref_id in _extract_reference_ids(msg):
            matched_row = history_store.get_by_message_id(ref_id)
            if matched_row:
                break

        if not matched_row and sender_email:
            for row in history_store.recent_sent_rows():
                if row.get("email_attempted", "").strip().lower() == sender_email:
                    matched_row = row
                    break

        if not matched_row:
            continue

        message_id = matched_row.get("message_id", "")
        if learning_store.has_message_event(message_id, "replied"):
            continue

        history_store.update_by_message_id(
            message_id=message_id,
            new_status="replied",
            failure_reason="reply_detected",
        )

        learning_store.append(
            LearningEvent(
                event_type="replied",
                company_normalized=matched_row.get("company_normalized", ""),
                domain=matched_row.get("domain", ""),
                email_pattern=matched_row.get("email_pattern", ""),
                email=matched_row.get("email_attempted", ""),
                message_id=message_id,
                source="reply_parser",
            )
        )
        updated_rows.append(matched_row)

    return updated_rows