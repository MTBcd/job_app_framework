"""Background worker: polls the jobs table and runs pipeline jobs.

Run:  python -m jobapp.worker
"""
from __future__ import annotations

import logging
import time

from jobapp.db import get_sessionmaker
from jobapp.services import queue
from jobapp.services.pipeline import run_job

logger = logging.getLogger("jobapp.worker")

POLL_SECONDS = 2.0


def process_one() -> bool:
    """Claim and run a single job. Returns True if a job was processed."""
    maker = get_sessionmaker()
    with maker() as session:
        job = queue.claim_next(session)
        if job is None:
            session.rollback()
            return False
        try:
            run_job(session, job.kind, job.payload)
            queue.mark_done(session, job)
            session.commit()
            logger.info("job done: %s %s", job.kind, job.id)
        except Exception as exc:  # noqa: BLE001 — worker must survive any job error
            session.rollback()
            with maker() as retry_session:
                failed = retry_session.get(type(job), job.id)
                if failed is not None:
                    queue.mark_failed(retry_session, failed, str(exc))
                    retry_session.commit()
            logger.exception("job failed: %s %s", job.kind, job.id)
        return True


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger.info("worker started")
    while True:
        if not process_one():
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
