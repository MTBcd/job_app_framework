"""FastAPI application factory.

Run locally:  uvicorn jobapp.api.app:app --reload
"""
from __future__ import annotations

from fastapi import FastAPI

from jobapp.api.routes.applications import router as applications_router
from jobapp.api.routes.cv import router as cv_router
from jobapp.api.routes.ui import router as ui_router
from jobapp.settings import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="Job Application Copilot API",
        version="0.1.0",
        docs_url="/docs" if settings.app_env != "production" else None,
    )
    application.include_router(applications_router)
    application.include_router(cv_router)
    application.include_router(ui_router)

    if settings.app_env == "local":
        # Dev convenience until Alembic lands with the managed Postgres.
        from jobapp.db import get_engine
        from jobapp.db.models import Base

        Base.metadata.create_all(get_engine())

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "env": settings.app_env}

    return application


app = create_app()
