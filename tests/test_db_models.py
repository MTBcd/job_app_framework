"""Schema smoke tests: the MVP models create, relate, and round-trip."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from jobapp.db.models import (
    Application,
    Base,
    Company,
    Contact,
    EmailCandidate,
    EmailPattern,
    Event,
    Job,
    MailboxSettings,
    Suppression,
    User,
)


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _user(session) -> User:
    user = User(clerk_user_id="clerk_123", email="jane@example.com")
    session.add(user)
    session.flush()
    return user


def test_full_application_graph_round_trips(session):
    user = _user(session)
    company = Company(user_id=user.id, name="Acme Corp", name_normalized="acme",
                      domain="acme.com", domain_source="from_company_override")
    session.add(company)
    session.flush()

    contact = Contact(user_id=user.id, company_id=company.id,
                      first_name="John", last_name="Smith", full_name="John Smith")
    session.add(contact)
    session.flush()

    candidate = EmailCandidate(
        contact_id=contact.id,
        email="john.smith@acme.com",
        pattern="first.last",
        confidence=0.78,
        reasoning=["pattern=first.last", "trusted_existing_domain"],
        is_selected=True,
    )
    session.add(candidate)

    application = Application(
        user_id=user.id, company_id=company.id, contact_id=contact.id,
        status="needs_review", email_to="john.smith@acme.com",
        subject="Application", body="Dear John...",
        review_reasons=["low_email_confidence"],
    )
    session.add(application)
    session.commit()

    loaded = session.scalars(select(Contact)).one()
    assert loaded.company.name == "Acme Corp"
    assert loaded.email_candidates[0].reasoning == [
        "pattern=first.last", "trusted_existing_domain",
    ]
    assert session.scalars(select(Application)).one().status == "needs_review"


def test_learning_event_carries_v0_weights(session):
    user = _user(session)
    session.add(Event(user_id=user.id, type="replied", weight=4.0,
                      domain="acme.com", email_pattern="first.last"))
    session.commit()
    event = session.scalars(select(Event)).one()
    assert (event.weight, event.domain, event.email_pattern) == (
        4.0, "acme.com", "first.last",
    )


def test_global_pattern_seed_rows_have_null_user(session):
    session.add(EmailPattern(user_id=None, domain="gs.com", pattern="first.last",
                             source="curated_v0", confidence=0.95))
    session.commit()
    pattern = session.scalars(select(EmailPattern)).one()
    assert pattern.user_id is None
    assert pattern.source == "curated_v0"


def test_supporting_tables_insert(session):
    user = _user(session)
    session.add_all([
        Suppression(user_id=user.id, value="bounced@acme.com", reason="hard_bounce"),
        MailboxSettings(user_id=user.id, username="jane@gmail.com",
                        password_encrypted="enc", dry_run=True),
        Job(user_id=user.id, kind="infer_emails", payload={"company_id": "x"}),
    ])
    session.commit()
    assert session.scalars(select(MailboxSettings)).one().dry_run is True
    assert session.scalars(select(Job)).one().status == "queued"
