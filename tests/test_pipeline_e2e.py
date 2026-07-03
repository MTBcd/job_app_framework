"""End-to-end: API create → worker runs pipeline → V0 inference persisted."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """App + worker against an isolated SQLite database."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")

    from jobapp import settings as settings_module
    from jobapp import db as db_module

    settings_module.get_settings.cache_clear()
    db_module.get_engine.cache_clear()
    db_module.get_sessionmaker.cache_clear()

    from jobapp.api.app import create_app

    yield TestClient(create_app())

    settings_module.get_settings.cache_clear()
    db_module.get_engine.cache_clear()
    db_module.get_sessionmaker.cache_clear()


HEADERS = {"X-Dev-User-Email": "founder@test.io"}


def _drain_jobs():
    from jobapp.worker import process_one

    while process_one():
        pass


def test_auth_required(client):
    assert client.get("/applications").status_code == 401


def test_create_prepare_review_flow(client):
    # CV upload
    response = client.post(
        "/cv",
        json={"content_text": "Quantitative analyst with Python, risk modelling " * 3},
        headers=HEADERS,
    )
    assert response.status_code == 201

    # Create application → queued for the pipeline
    response = client.post(
        "/applications",
        json={
            "company_name": "Goldman Sachs",
            "role": "Quantitative Analyst",
            "contact_name": "John Smith",
            "contact_title": "Head of Quant Research",
        },
        headers=HEADERS,
    )
    assert response.status_code == 201
    application_id = response.json()["id"]
    assert response.json()["status"] == "processing"

    # Worker runs the V0 engine
    _drain_jobs()

    # Review-ready pack with real inference results
    pack = client.get(f"/applications/{application_id}", headers=HEADERS).json()
    assert pack["status"] == "needs_review"
    assert pack["pipeline_stage"] == "done"
    # Curated V0 override: Goldman Sachs → gs.com; top pattern first.last
    assert pack["email_to"] == "john.smith@gs.com"
    assert len(pack["candidates"]) == 9
    top = pack["candidates"][0]
    assert top["is_selected"] is True
    assert top["pattern"] == "first.last"
    assert top["confidence"] >= 0.72  # trusted override domain → no review flag
    assert any("pattern=first.last" in reason for reason in top["reasoning"])
    assert "low_email_confidence" not in pack["review_reasons"]
    # Honest non-AI fallback until the provider is configured
    assert "ai_not_configured" in pack["review_reasons"]
    assert "Goldman Sachs" in pack["subject"]

    # Status endpoint
    status = client.get(
        f"/applications/{application_id}/status", headers=HEADERS
    ).json()
    assert status == {"status": "needs_review", "pipeline_stage": "done"}


def test_duplicate_company_rejected(client):
    first = client.post(
        "/applications",
        json={"company_name": "Acme Rockets", "role": "Quant"},
        headers=HEADERS,
    )
    assert first.status_code == 201
    duplicate = client.post(
        "/applications", json={"company_name": "Acme Rockets"}, headers=HEADERS
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["existing_id"] == first.json()["id"]


def test_free_plan_cap(client):
    for name in ("One Corp", "Two Corp", "Three Corp"):
        assert (
            client.post(
                "/applications", json={"company_name": name}, headers=HEADERS
            ).status_code
            == 201
        )
    over_cap = client.post(
        "/applications", json={"company_name": "Four Corp"}, headers=HEADERS
    )
    assert over_cap.status_code == 402


def test_heuristic_domain_flags_review(client):
    response = client.post(
        "/applications",
        json={"company_name": "Zeta Widgets", "contact_name": "Ann Lee"},
        headers=HEADERS,
    )
    application_id = response.json()["id"]
    _drain_jobs()
    pack = client.get(f"/applications/{application_id}", headers=HEADERS).json()
    # zetawidgets.com is a guess → V0 heuristic penalty → must flag review
    assert pack["email_to"] == "ann.lee@zetawidgets.com"
    assert "heuristic_domain" in pack["review_reasons"]
    assert "low_email_confidence" in pack["review_reasons"]
