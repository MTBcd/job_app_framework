"""Contact selection: contextual, scored, reasoned (spec: never hide why)."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from jobapp.db.models import Base, Company, Contact, Opportunity, User
from jobapp.services.contact_selection import select_best_contact


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _setup(session, contacts: list[tuple[str, str, str]], title="Data Scientist"):
    user = User(clerk_user_id="c1", email="u@test.io")
    session.add(user)
    session.flush()
    company = Company(user_id=user.id, name="Acme", name_normalized="acme")
    session.add(company)
    session.flush()
    for first, last, contact_title in contacts:
        session.add(
            Contact(
                user_id=user.id, company_id=company.id, first_name=first,
                last_name=last, full_name=f"{first} {last}", title=contact_title,
            )
        )
    opportunity = Opportunity(user_id=user.id, company_id=company.id, title=title)
    session.add(opportunity)
    session.flush()
    return opportunity


def test_recruiter_beats_ceo_at_large_company(session):
    opportunity = _setup(
        session,
        [("Alice", "Big", "CEO"), ("Rita", "Hire", "Senior Talent Acquisition Partner")],
    )
    best = select_best_contact(session, opportunity, company_size=50_000)
    assert best.contact.last_name == "Hire"
    assert "owns recruiting" in best.rationale
    assert best.components["recruiting_responsibility"] > 0


def test_founder_reasonable_for_small_company(session):
    opportunity = _setup(session, [("Fred", "Founder", "Co-Founder")])
    best = select_best_contact(session, opportunity, company_size=15)
    assert best.contact.last_name == "Founder"
    assert best.components["seniority_appropriateness"] > 0


def test_ceo_penalized_for_large_company(session):
    opportunity = _setup(
        session, [("Alice", "Big", "CEO"), ("Dan", "Data", "Head of Data")]
    )
    best = select_best_contact(session, opportunity, company_size=50_000)
    assert best.contact.last_name == "Data"
    assert "Head of Data" in best.rationale


def test_role_overlap_scores(session):
    opportunity = _setup(
        session,
        [("Pat", "Ops", "Head of Operations"), ("Dana", "Sci", "Data Science Manager")],
        title="Data Science",
    )
    best = select_best_contact(session, opportunity)
    assert best.contact.last_name == "Sci"
    assert best.components["role_relevance"] > 0


def test_no_contacts_returns_none(session):
    opportunity = _setup(session, [])
    assert select_best_contact(session, opportunity) is None


def test_rationale_is_user_facing(session):
    opportunity = _setup(session, [("Jane", "Smith", "Head of Data")], title="Data Science")
    best = select_best_contact(session, opportunity)
    assert best.rationale.startswith("Recommended contact: Jane Smith — Head of Data.")
    assert "Selected because" in best.rationale
