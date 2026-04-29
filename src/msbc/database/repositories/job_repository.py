"""
Repository for ``Job`` records.

All database access for the ``jobs`` table is centralised here.
API endpoint handlers call these methods to create jobs and poll status;
background-task workers call them to update lifecycle state.

Usage::

    from sqlalchemy.orm import Session
    from src.msbc.database.repositories import JobRepository

    repo = JobRepository(db)
    job = repo.create_job(job_type="requirement_extraction")
    repo.mark_processing(job.id)
    repo.mark_completed(job.id, result={...})
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from src.msbc.database.repositories.base_repository import BaseRepository
from src.msbc.models.entities.job import Job


class JobRepository(BaseRepository[Job]):
    """CRUD + lifecycle operations for the ``jobs`` table."""

    def __init__(self, db: Session) -> None:
        super().__init__(Job, db)

    # ── Write ─────────────────────────────────────────────────────────────────

    def create_job(self, *, job_type: str) -> Job:
        """
        Insert a new job with ``status="pending"`` and return it.

        Parameters
        ----------
        job_type:
            One of ``"requirement_extraction"`` or ``"frontend_planning"``.
        """
        record = Job(job_type=job_type, status="pending")
        return self.create(record)

    def mark_processing(self, job_id: str) -> Job | None:
        """Transition a job from ``pending`` → ``processing``."""
        return self._update_status(job_id, "processing")

    def mark_completed(self, job_id: str, *, result: dict[str, Any]) -> Job | None:
        """Transition a job to ``completed`` and store the result payload."""
        job = self._db.get(Job, job_id)
        if job is None:
            return None
        job.status = "completed"
        job.result = result
        job.updated_at = datetime.now(timezone.utc)
        self._db.flush()
        self._db.refresh(job)
        return job

    def mark_failed(self, job_id: str, *, error_message: str) -> Job | None:
        """Transition a job to ``failed`` and store the error description."""
        job = self._db.get(Job, job_id)
        if job is None:
            return None
        job.status = "failed"
        job.error_message = error_message
        job.updated_at = datetime.now(timezone.utc)
        self._db.flush()
        self._db.refresh(job)
        return job

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_by_job_id(self, job_id: str) -> Job | None:
        """Fetch a single job by its UUID string, or ``None`` if not found."""
        return self._db.get(Job, job_id)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _update_status(self, job_id: str, status: str) -> Job | None:
        job = self._db.get(Job, job_id)
        if job is None:
            return None
        job.status = status
        job.updated_at = datetime.now(timezone.utc)
        self._db.flush()
        self._db.refresh(job)
        return job
