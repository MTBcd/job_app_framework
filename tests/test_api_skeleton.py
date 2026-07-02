"""API skeleton smoke test."""
from __future__ import annotations

from fastapi.testclient import TestClient

from jobapp.api.app import create_app


def test_health_endpoint():
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
