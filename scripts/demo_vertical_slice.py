"""End-to-end demo of the V1 vertical slice with deterministic fake providers.

Run from the repo root:

    PYTHONPATH=src python3 scripts/demo_vertical_slice.py

No credentials, network, or LLM keys required. Uses a throwaway SQLite file.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
_db = Path(tempfile.mkdtemp()) / "demo.db"
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_db}")
os.environ.setdefault("APP_ENV", "local")
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ.pop("SMTP_USERNAME", None)
os.environ.pop("SMTP_PASSWORD", None)


def step(number: int, title: str) -> None:
    print(f"\n{'─' * 60}\nSTEP {number:>2} · {title}\n{'─' * 60}")


def main() -> None:
    from jobapp.db import get_engine, get_sessionmaker
    from jobapp.db.models import Base, Contact, Document, User
    from jobapp.providers import get_ai_provider
    from jobapp.providers.fakes import FakeEmailProvider
    from jobapp.services.applications import create_application
    from jobapp.services.pipeline import prepare_application
    from jobapp.services.sending import approve, record_reply, send

    Base.metadata.create_all(get_engine())
    session = get_sessionmaker()()

    step(1, "Create test user")
    user = User(clerk_user_id="demo", email="demo@example.com", full_name="Jane Doe")
    session.add(user)
    session.flush()
    print(f"user: {user.email}")

    step(2, "Candidate profile from CV (parsed once, reviewable)")
    cv_text = "Jane Doe\nSenior Data Scientist\nPython Machine Learning SQL Leadership"
    profile, _ = get_ai_provider().parse_cv(cv_text)
    session.add(Document(user_id=user.id, kind="cv", content_text=cv_text,
                         parsed_profile=profile))
    print(f"identity: {profile['identity']}  skills: {profile['skills'][:5]}")

    step(3, "Company-only spontaneous opportunity (no job description)")
    application = create_application(session, user,
                                     company_name="Northwind Analytics",
                                     notes="spontaneous application")
    print(f"application: {application.id}  status: {application.status}")

    step(5, "Seed contact candidates (import path)")
    for first, last, title in [("Carl", "Chief", "CEO"),
                               ("Rita", "Recruit", "Head of Talent Acquisition")]:
        session.add(Contact(user_id=user.id, company_id=application.company_id,
                            first_name=first, last_name=last,
                            full_name=f"{first} {last}", title=title))
    session.flush()

    step(4, "Pipeline: research → contact selection → inference → plan → email")
    prepare_application(session, application.id)
    session.refresh(application)

    from jobapp.db.models import ResearchBrief
    from sqlalchemy import select
    brief = session.scalars(select(ResearchBrief).where(
        ResearchBrief.opportunity_id == application.opportunity_id)).one()
    print("research provenance:")
    for fact in brief.facts:
        print(f"  · {fact['fact']}  [{fact['source']} @ {fact['retrieved_at']}, "
              f"confidence {fact['confidence']}]")

    step(6, "Contact selection reasoning (visible, never hidden)")
    print(f"  {application.contact_rationale}")

    step(7, "Email resolution provenance (V0 engine, honest labels)")
    print(f"  {application.email_to}")
    print(f"  source={application.email_source}  pattern={application.email_pattern}  "
          f"confidence={application.email_confidence}  label='{application.email_label}'")

    step(8, "Personalization plan")
    for key, value in application.personalization_plan.items():
        print(f"  {key}: {value}")

    step(9, "Tailored draft (deterministic fake AI — assembled from inputs only)")
    print(f"  subject: {application.subject}")
    print("  " + application.body.replace("\n", "\n  "))

    step(10, "User reviews and edits")
    edited = application.body + "\nP.S. Happy to share my portfolio."
    application.body = edited
    print("  user appended a P.S.")

    step(11, "Approve — snapshot frozen")
    approve(session, application)
    print(f"  approved at {application.approved_at}")
    application.body = "TAMPERED AFTER APPROVAL (must never be sent)"

    step(12, "Send via EmailProvider (fake transport records exact payload)")
    send(session, application, user)
    outbound = FakeEmailProvider.shared().sent[-1]
    print(f"  provider received subject: {outbound.subject}")
    assert outbound.body == edited, "BUG: sent content differs from approved!"
    print("  ✓ provider received the EXACT approved body (tamper ignored)")

    step(13, "Send event persisted")
    print(f"  status={application.status}  message_id={application.message_id}")

    step(14, "Simulate a reply")
    record_reply(session, application,
                 "Thanks Jane — are you free Tuesday for a quick call?")

    step(15, "Application status updated")
    print(f"  status={application.status}  preview='{application.reply_preview}'")

    step(16, "Learning events — privacy-safe dimensions only")
    from jobapp.db.models import Event
    for event in session.scalars(select(Event)).all():
        print(f"  {event.type:<8} weight={event.weight:+.1f}  domain={event.domain}  "
              f"pattern={event.email_pattern}  payload={event.payload}")

    session.commit()
    session.close()
    print(f"\n{'═' * 60}\nVertical slice complete. Database: {_db}\n{'═' * 60}")


if __name__ == "__main__":
    main()
