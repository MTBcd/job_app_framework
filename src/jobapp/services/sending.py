"""Approval, sending, replies, learning events.

The V0 review-before-send defect is fixed here structurally: approval takes
an immutable snapshot (approved_subject/approved_body), and send() consumes
ONLY that snapshot — it never re-runs research, inference, or generation.

Privacy boundary (documented in docs/api.md): learning events carry only
domain + email_pattern + weight. No names, no addresses, no CV content —
cross-user aggregation can therefore never leak personal data.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jobapp.cleaning import extract_domain, is_valid_email
from jobapp.db.models import Application, Company, Event, Suppression, User
from jobapp.providers import EmailProvider, OutboundMessage, get_email_provider
from jobapp.settings import get_settings

# V0 learning weights, preserved (src/jobapp/learning.py).
EVENT_WEIGHTS = {
    "sent": 1.0,
    "delivered": 1.5,
    "replied": 4.0,
    "positive_reply": 4.0,
    "soft_bounce": -0.75,
    "hard_bounce": -3.0,
    "failed_send": -1.0,
}


class SendBlocked(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _learning_event(
    session: Session, application: Application, event_type: str
) -> Event:
    company = session.get(Company, application.company_id)
    event = Event(
        user_id=application.user_id,
        application_id=application.id,
        type=event_type,
        weight=EVENT_WEIGHTS.get(event_type, 0.0),
        domain=company.domain if company else "",
        email_pattern=application.email_pattern,
        payload={},  # intentionally empty — see privacy boundary above
    )
    session.add(event)
    return event


def approve(
    session: Session,
    application: Application,
    *,
    subject: str | None = None,
    body: str | None = None,
) -> Application:
    if application.status not in {"ready_for_review", "draft"}:
        raise SendBlocked(f"cannot approve from status {application.status}")
    if subject is not None:
        application.subject = subject
    if body is not None:
        application.body = body
    if not application.subject.strip() or not application.body.strip():
        raise SendBlocked("empty_subject_or_body")

    application.approved_subject = application.subject
    application.approved_body = application.body
    application.approved_at = datetime.now(timezone.utc)
    application.status = "approved"
    session.flush()
    return application


def _preflight(session: Session, application: Application, user: User) -> None:
    if application.status != "approved":
        raise SendBlocked("not_approved")
    if application.approved_subject is None or application.approved_body is None:
        raise SendBlocked("missing_approved_snapshot")

    recipient = application.email_to.strip().lower()
    if not is_valid_email(recipient):
        raise SendBlocked("invalid_recipient")

    domain = extract_domain(recipient)
    blocked = {
        item.strip().lower()
        for item in get_settings().blocked_recipient_domains.split(",")
        if item.strip()
    }
    if domain in blocked:
        raise SendBlocked("blocked_consumer_domain")

    suppressed = session.scalars(
        select(Suppression).where(
            Suppression.user_id == user.id,
            Suppression.value.in_([recipient, domain]),
        )
    ).first()
    if suppressed is not None:
        raise SendBlocked("suppressed_recipient")

    duplicate = session.scalars(
        select(Application).where(
            Application.user_id == user.id,
            Application.id != application.id,
            func.lower(Application.email_to) == recipient,
            Application.status.in_(["sent", "replied", "positive_reply", "interview"]),
        )
    ).first()
    if duplicate is not None:
        raise SendBlocked("duplicate_recipient")

    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    sent_today = len(
        session.scalars(
            select(Event.id).where(
                Event.user_id == user.id,
                Event.type == "sent",
                Event.created_at >= today_start,
            )
        ).all()
    )
    if sent_today >= get_settings().default_daily_send_cap:
        raise SendBlocked("daily_cap_reached")


def send(
    session: Session,
    application: Application,
    user: User,
    provider: EmailProvider | None = None,
) -> Application:
    """Sends the EXACT approved snapshot. Never regenerates."""
    provider = provider or get_email_provider()
    _preflight(session, application, user)

    result = provider.send(
        OutboundMessage(
            to_email=application.email_to,
            subject=application.approved_subject,
            body=application.approved_body,
            from_name=user.full_name,
        )
    )
    application.message_id = result.message_id
    application.sent_at = datetime.now(timezone.utc)
    application.status = "sent"
    _learning_event(session, application, "sent")
    session.flush()
    return application


def record_reply(
    session: Session,
    application: Application,
    reply_text: str,
    *,
    positive: bool = False,
) -> Application:
    event_type = "positive_reply" if positive else "replied"
    application.status = event_type
    application.last_reply_at = datetime.now(timezone.utc)
    application.reply_preview = reply_text.strip()[:300]
    _learning_event(session, application, event_type)
    session.flush()
    return application
