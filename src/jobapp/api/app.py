"""FastAPI application factory.

Run locally:  uvicorn jobapp.api.app:app --reload
"""
from __future__ import annotations

from fastapi import FastAPI

from jobapp.settings import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="Job Application Copilot API",
        version="0.1.0",
        docs_url="/docs" if settings.app_env != "production" else None,
    )

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "env": settings.app_env}

    return application


app = create_app()
