"""Postgres-backed job queue (spec: no Celery/Redis at this scale).

Postgres gets real FOR UPDATE SKIP LOCKED semantics; SQLite (tests/dev)
falls back to plain FOR UPDATE, which is fine single-worker.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from jobapp.db.models import Job

MAX_ATTEMPTS = 3


def enqueue(session: Session, kind: str, payload: dict, user_id: str | None = None) -> Job:
    job = Job(kind=kind, payload=payload, user_id=user_id)
    session.add(job)
    session.flush()
    return job


def claim_next(session: Session) -> Job | None:
    now = datetime.now(timezone.utc)
    statement = (
        select(Job)
        .where(Job.status == "queued")
        .where((Job.run_after.is_(None)) | (Job.run_after <= now))
        .order_by(Job.created_at)
        .limit(1)
        .with_for_update(skip_locked=session.bind.dialect.name == "postgresql")
    )
    job = session.scalars(statement).first()
    if job is None:
        return None
    job.status = "running"
    job.locked_at = now
    job.attempts += 1
    session.flush()
    return job


def mark_done(session: Session, job: Job) -> None:
    job.status = "done"
    session.flush()


def mark_failed(session: Session, job: Job, error: str) -> None:
    job.last_error = error[:2000]
    job.status = "failed" if job.attempts >= MAX_ATTEMPTS else "queued"
    job.locked_at = None
    session.flush()
