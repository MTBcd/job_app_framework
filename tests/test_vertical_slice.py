"""The complete vertical slice (spec: 16 steps), end-to-end with fakes.

Also carries the two contract regression tests:
- the EXACT approved email is what the send provider receives (fixes the
  V0 review-before-send defect, audit 2.3 item 1)
- learning events contain no cross-user personal data (privacy boundary)
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/slice.db")
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.delenv("SMTP_USERNAME", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)

    from jobapp import db as db_module
    from jobapp import settings as settings_module
    from jobapp.providers.fakes import FakeEmailProvider

    settings_module.get_settings.cache_clear()
    db_module.get_engine.cache_clear()
    db_module.get_sessionmaker.cache_clear()
    FakeEmailProvider.reset()

    from jobapp.api.app import create_app

    yield TestClient(create_app())

    settings_module.get_settings.cache_clear()
    db_module.get_engine.cache_clear()
    db_module.get_sessionmaker.cache_clear()
    FakeEmailProvider.reset()


HEADERS = {"X-Dev-User-Email": "slice@test.io"}


def _drain():
    from jobapp.worker import process_one

    while process_one():
        pass


def _session():
    from jobapp.db import get_sessionmaker

    return get_sessionmaker()()


def test_complete_vertical_slice(env):
    client = env

    # 1-2: user (dev auth) + candidate profile from CV, reviewable/correctable
    upload = client.post(
        "/cv",
        json={
            "content_text": "Jane Doe\nSenior Data Scientist\n"
            "Python Machine Learning Forecasting SQL Leadership",
            "filename": "cv.txt",
        },
        headers=HEADERS,
    )
    assert upload.status_code == 201
    profile = upload.json()["parsed_profile"]
    assert profile["identity"]["name"] == "Jane Doe"
    assert "Python" in profile["skills"]

    # user corrects the extracted profile — corrected version is source of truth
    profile["skills"].append("Statistics")
    corrected = client.put(
        "/cv/profile", json={"parsed_profile": profile}, headers=HEADERS
    )
    assert "Statistics" in corrected.json()["parsed_profile"]["skills"]

    # 3: company-only spontaneous opportunity (no job description — first-class)
    created = client.post(
        "/applications",
        json={"company_name": "Northwind Analytics", "notes": "spontaneous"},
        headers=HEADERS,
    )
    assert created.status_code == 201
    application_id = created.json()["id"]

    # 5: seed contact candidates (import path), including a trap: a CEO who
    # must NOT be selected over the recruiter at a large company
    with _session() as session:
        from jobapp.db.models import Application, Company, Contact

        application = session.get(Application, application_id)
        for first, last, title in [
            ("Carl", "Chief", "CEO"),
            ("Rita", "Recruit", "Head of Talent Acquisition"),
        ]:
            session.add(
                Contact(
                    user_id=application.user_id,
                    company_id=application.company_id,
                    first_name=first,
                    last_name=last,
                    full_name=f"{first} {last}",
                    title=title,
                )
            )
        session.commit()

    # 4, 6, 7, 8, 9: research → contact selection → inference → plan → email
    _drain()
    pack = client.get(f"/applications/{application_id}", headers=HEADERS).json()
    assert pack["status"] == "ready_for_review"

    # research provenance visible (4)
    assert pack["research"]["provider"] == "fake"
    for fact in pack["research"]["facts"]:
        assert fact["source"]
        assert fact["retrieved_at"]
        assert 0 <= fact["confidence"] <= 1

    # contact selection reasoned (6)
    assert "Rita Recruit" in pack["contact_rationale"]
    assert "Selected because" in pack["contact_rationale"]

    # inference provenance visible, never overstated (7)
    assert pack["email_to"] == "rita.recruit@northwindanalytics.com"
    assert pack["email_source"] == "heuristic"
    assert pack["email_label"] in {
        "High-confidence inference", "Low-confidence inference",
    }
    assert pack["email_label"] != "Verified"
    assert pack["candidates"][0]["reasoning"]

    # personalization plan grounded in provided inputs only (8)
    plan = pack["personalization_plan"]
    assert plan["call_to_action"] == "short_intro_call"
    assert "unverified_company_claims" in plan["do_not_mention"]

    # 10: review and edit — the human's words, not the model's
    edited_body = pack["body"] + "\nP.S. I loved your recent case study."
    edit = client.patch(
        f"/applications/{application_id}",
        json={"body": edited_body},
        headers=HEADERS,
    )
    assert edit.status_code == 200

    # 11: approve the EXACT email
    approve = client.post(
        f"/applications/{application_id}/approve", json={}, headers=HEADERS
    )
    assert approve.status_code == 200

    # post-approval edits must NOT alter what gets sent (V0 defect regression)
    client.patch(
        f"/applications/{application_id}",
        json={"body": "TAMPERED AFTER APPROVAL"},
        headers=HEADERS,
    )

    # 12-13: send through the provider interface; send event persisted
    sent = client.post(f"/applications/{application_id}/send", headers=HEADERS)
    assert sent.status_code == 200
    assert sent.json()["status"] == "sent"
    assert sent.json()["message_id"].endswith("@fake.jobapp>")

    from jobapp.providers.fakes import FakeEmailProvider

    outbound = FakeEmailProvider.shared().sent
    assert len(outbound) == 1
    # THE contract: provider received the approved snapshot, byte for byte
    assert outbound[0].body == edited_body
    assert "TAMPERED" not in outbound[0].body
    assert outbound[0].to_email == "rita.recruit@northwindanalytics.com"

    # 14-15: simulate a reply → status updated, preview stored
    with _session() as session:
        from jobapp.db.models import Application
        from jobapp.services.sending import record_reply

        record_reply(session, session.get(Application, application_id),
                     "Thanks Jane — let's talk next week. Are you free Tuesday?")
        session.commit()

    pack = client.get(f"/applications/{application_id}", headers=HEADERS).json()
    assert pack["status"] == "replied"
    assert "free Tuesday" in pack["reply_preview"]

    # 16: learning events are safe — domain+pattern+weight only, no PII
    with _session() as session:
        from jobapp.db.models import Event

        events = session.scalars(select(Event)).all()
        types = sorted(event.type for event in events)
        assert types == ["replied", "sent"]
        for event in events:
            assert event.domain == "northwindanalytics.com"
            assert event.email_pattern == "first.last"
            payload_json = json.dumps(event.payload)
            assert event.payload == {}
            assert "@" not in payload_json
            assert "Jane" not in payload_json and "Rita" not in payload_json
        assert {event.weight for event in events} == {1.0, 4.0}


def test_send_requires_approval(env):
    client = env
    client.post("/cv", json={"content_text": "Jane Doe\nData person with skills"},
                headers=HEADERS)
    created = client.post(
        "/applications",
        json={"company_name": "Beta LLC", "contact_name": "Ann Lee"},
        headers=HEADERS,
    )
    application_id = created.json()["id"]
    _drain()
    blocked = client.post(f"/applications/{application_id}/send", headers=HEADERS)
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "not_approved"


def test_duplicate_recipient_blocked(env):
    client = env
    client.post("/cv", json={"content_text": "Jane Doe\nData person with skills"},
                headers=HEADERS)

    first = client.post(
        "/applications",
        json={"company_name": "Gamma Corp", "role": "Analyst",
              "contact_name": "Bob Ray"},
        headers=HEADERS,
    )
    first_id = first.json()["id"]
    _drain()
    client.post(f"/applications/{first_id}/approve", json={}, headers=HEADERS)
    assert client.post(f"/applications/{first_id}/send", headers=HEADERS).status_code == 200

    # same person again via a second application → preflight must block
    second = client.post(
        "/applications",
        json={"company_name": "Gamma Corp", "role": "Senior Analyst",
              "contact_name": "Bob Ray"},
        headers=HEADERS,
    )
    second_id = second.json()["id"]
    _drain()
    client.post(f"/applications/{second_id}/approve", json={}, headers=HEADERS)
    blocked = client.post(f"/applications/{second_id}/send", headers=HEADERS)
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "duplicate_recipient"
