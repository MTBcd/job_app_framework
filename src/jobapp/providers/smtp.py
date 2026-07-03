"""SMTP EmailProvider adapter (Gmail app-password path for the MVP).

Thin transport only — validation, suppression, dedupe, and caps live in
services.sending, never here. Uses env-level SMTP settings for now; the
per-user mailbox_settings wiring arrives with the settings UI.
"""
from __future__ import annotations

import os
import smtplib
import uuid
from email.message import EmailMessage

from jobapp.providers import OutboundMessage, SendResult


def smtp_configured() -> bool:
    return bool(os.getenv("SMTP_USERNAME") and os.getenv("SMTP_PASSWORD"))


class SmtpEmailProvider:
    def send(self, message: OutboundMessage) -> SendResult:  # pragma: no cover — needs live SMTP
        host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        port = int(os.getenv("SMTP_PORT", "587"))
        username = os.getenv("SMTP_USERNAME", "")
        password = os.getenv("SMTP_PASSWORD", "")
        from_email = message.from_email or os.getenv("SMTP_FROM_EMAIL", username)

        email_message = EmailMessage()
        email_message["From"] = (
            f"{message.from_name} <{from_email}>" if message.from_name else from_email
        )
        email_message["To"] = message.to_email
        email_message["Subject"] = message.subject
        message_id = f"<{uuid.uuid4()}@{from_email.split('@')[-1] or 'jobapp'}>"
        email_message["Message-ID"] = message_id
        email_message.set_content(message.body)

        with smtplib.SMTP(host, port) as server:
            server.starttls()
            server.login(username, password)
            server.send_message(email_message)

        return SendResult(message_id=message_id, provider="smtp")
