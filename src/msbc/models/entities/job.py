"""
ORM entity: jobs table.

Each row represents one async job submitted by a client.  The two supported
job types are:

  * ``requirement_extraction``  — triggered by POST /requirement-extractor/parse
  * ``frontend_planning``       — triggered by POST /frontend-planner/plan

Columns
-------
id              UUID primary key (auto-generated) — returned as ``job_id``
job_type        Job category: "requirement_extraction" | "frontend_planning"
status          Lifecycle state: "pending" → "processing" → "completed" | "failed"
result          Full JSON result payload (populated when status = "completed")
error_message   Human-readable error string (populated when status = "failed")
created_at      Row creation timestamp (UTC, auto-set by DB)
updated_at      Last-modified timestamp (UTC, updated manually on every write)
"""

from __future__ import annotations

import uuid

from sqlalchemy import DateTime, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from src.msbc.database.base import Base


def _uuid_col():
    """Return a UUID column type compatible with both PostgreSQL and SQLite."""
    if settings.DATABASE_URL.startswith("sqlite"):
        return String(36)
    from sqlalchemy.dialects.postgresql import UUID
    return UUID(as_uuid=True)


class Job(Base):
    """Persisted record for a single async job."""

    __tablename__ = "jobs"

    # ── Primary key ───────────────────────────────────────────────────────────
    id: Mapped[str] = mapped_column(
        _uuid_col(),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Unique job identifier returned to the caller immediately",
    )

    # ── Classification ────────────────────────────────────────────────────────
    job_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="requirement_extraction | frontend_planning",
    )

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
        comment="pending | processing | completed | failed",
    )

    # ── Payload ───────────────────────────────────────────────────────────────
    result: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        comment="Full result payload — populated when status = completed",
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Error description — populated when status = failed",
    )

    # ── Audit ─────────────────────────────────────────────────────────────────
    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="UTC timestamp of job creation",
    )

    updated_at: Mapped[str] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="UTC timestamp of last status change (updated explicitly by the repository)",
    )

    # ── Repr ──────────────────────────────────────────────────────────────────
    def __repr__(self) -> str:
        return (
            f"<Job id={self.id!s} type={self.job_type!r} status={self.status!r}>"
        )
