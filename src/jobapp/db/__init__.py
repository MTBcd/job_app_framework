"""Database engine and session management."""
from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from jobapp.settings import get_settings


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    if settings.database_url.startswith("sqlite"):
        # NullPool: a fresh connection per session avoids pooled-connection
        # file-lock interplay under the multi-threaded TestClient/worker mix.
        # Postgres (production) keeps the default QueuePool.
        return create_engine(
            settings.database_url,
            connect_args={"check_same_thread": False, "timeout": 15},
            poolclass=NullPool,
        )
    return create_engine(settings.database_url, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    with get_sessionmaker()() as session:
        yield session
