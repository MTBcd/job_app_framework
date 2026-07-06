"""Minimal review UI: full beta journey through server-rendered pages."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/ui.db")
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

    yield TestClient(create_app(), follow_redirects=True)

    settings_module.get_settings.cache_clear()
    db_module.get_engine.cache_clear()
    db_module.get_sessionmaker.cache_clear()
    FakeEmailProvider.reset()


PROFILE = {
    "full_name": "Maya Chen",
    "target_role": "Backend Engineer",
    "location": "Berlin",
    "headline": "Backend engineer, Python and Postgres in production",
    "experience_summary": "Two years building payment integrations",
    "skills": "Python, PostgreSQL, FastAPI",
    "proof_points": "built an internal returns dashboard\nopen-source CSV CLI",
    "constraints": "no fintech certification",
}

OPPORTUNITY = {
    "company_name": "Meridian Labs",
    "role": "Junior Backend Engineer",
    "jd_text": "Python, PostgreSQL, payments team",
    "notes": "",
    "contact_name": "Sara Novak",
    "contact_title": "Engineering Manager",
    "contact_email": "",
}


def _application_id(response) -> str:
    return str(response.url).rstrip("/").split("/")[-1]


def test_full_ui_journey(client):
    # dashboard prompts for profile first + shows fake-provider banner
    page = client.get("/ui")
    assert page.status_code == 200
    assert "deterministic fake" in page.text
    assert "creating your candidate profile" in page.text

    # profile form roundtrip
    assert client.get("/ui/profile").status_code == 200
    saved = client.post("/ui/profile", data=PROFILE)
    assert saved.status_code == 200  # redirected to /ui/new
    prefilled = client.get("/ui/profile")
    assert "Maya Chen" in prefilled.text
    assert "returns dashboard" in prefilled.text

    # opportunity -> inline pipeline -> review screen
    review = client.post("/ui/opportunity", data=OPPORTUNITY)
    assert review.status_code == 200
    application_id = _application_id(review)
    assert "Meridian Labs" in review.text          # company context
    assert "sara.novak@" in review.text            # inferred recipient
    assert "confidence" in review.text
    assert "Sara Novak" in review.text
    assert "ready for review" in review.text
    assert "Candidate proof points used" in review.text
    assert "Python" in review.text

    # edit, approve (freeze), then post-approval edits must not leak into send
    edited_body = "Hi Sara,\n\nEdited by the human reviewer.\n\nShort call?"
    client.post(f"/ui/applications/{application_id}/save",
                data={"subject": "Edited subject", "body": edited_body})
    approved = client.post(f"/ui/applications/{application_id}/approve")
    assert "frozen snapshot" in approved.text
    client.post(f"/ui/applications/{application_id}/save",
                data={"subject": "tampered", "body": "TAMPERED"})

    sent = client.post(f"/ui/applications/{application_id}/send")
    assert "sent (simulated)" in sent.text
    assert "Edited subject" in sent.text
    assert "Edited by the human reviewer." in sent.text
    assert "TAMPERED" not in sent.text.split("Sent (simulated)")[-1].split("Recipient")[0]

    from jobapp.providers.fakes import FakeEmailProvider

    outbound = FakeEmailProvider.shared().sent
    assert len(outbound) == 1
    assert outbound[0].body == edited_body
    assert outbound[0].subject == "Edited subject"

    # dashboard reflects final state
    assert "sent (simulated)" in client.get("/ui").text


def test_provided_contact_email_wins_over_inference(client):
    client.post("/ui/profile", data=PROFILE)
    data = dict(OPPORTUNITY, company_name="Beta LLC",
                contact_email="sara@beta-known.io")
    review = client.post("/ui/opportunity", data=data)
    assert "sara@beta-known.io" in review.text
    assert "Verified" in review.text


def test_send_requires_approval(client):
    client.post("/ui/profile", data=PROFILE)
    review = client.post("/ui/opportunity",
                         data=dict(OPPORTUNITY, company_name="Gamma Corp"))
    application_id = _application_id(review)
    blocked = client.post(f"/ui/applications/{application_id}/send")
    assert "Action blocked" in blocked.text
    assert "not_approved" in blocked.text


def test_demo_flow_end_to_end(client):
    review = client.post("/ui/demo")
    assert review.status_code == 200
    assert "Northwind Analytics" in review.text
    assert "Rita Recruit" in review.text           # recruiter beats CEO
    assert "rita.recruit@northwindanalytics.com" in review.text
    # demo re-run lands on the existing application instead of erroring
    again = client.post("/ui/demo")
    assert _application_id(again) == _application_id(review)


def test_ui_disabled_outside_local_env(client, monkeypatch):
    from jobapp import settings as settings_module

    monkeypatch.setenv("APP_ENV", "production")
    settings_module.get_settings.cache_clear()
    try:
        assert client.get("/ui").status_code == 404
    finally:
        monkeypatch.setenv("APP_ENV", "local")
        settings_module.get_settings.cache_clear()
