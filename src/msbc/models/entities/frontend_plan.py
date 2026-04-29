"""
ORM entity: frontend_plans table.

Each row represents one successful run of the Frontend Planner Agent.

Columns
-------
id                UUID primary key (auto-generated)
extraction_id     FK → requirement_extractions.id (the source extraction)
plan              Full structured plan JSON (one ModulePlan per item in the array)
usage             LLM token/cost usage summary (JSON)
created_at        Row creation timestamp (UTC, auto-set by the DB)
"""

from __future__ import annotations

import uuid

from sqlalchemy import DateTime, ForeignKey, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from src.msbc.database.base import Base


def _uuid_col():
    """Return a UUID column type compatible with both PostgreSQL and SQLite."""
    if settings.DATABASE_URL.startswith("sqlite"):
        return String(36)
    from sqlalchemy.dialects.postgresql import UUID
    return UUID(as_uuid=True)


class FrontendPlan(Base):
    """Persisted record for a single Frontend Planner Agent run."""

    __tablename__ = "frontend_plans"

    # ── Primary key ───────────────────────────────────────────────────────────
    id: Mapped[str] = mapped_column(
        _uuid_col(),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Unique plan identifier",
    )

    # ── Source extraction ─────────────────────────────────────────────────────
    extraction_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("requirement_extractions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="FK → requirement_extractions.id — the source extraction this plan was derived from",
    )

    # ── Payload ───────────────────────────────────────────────────────────────
    plan: Mapped[list] = mapped_column(
        JSON,
        nullable=False,
        comment="Full structured plan — array of ModulePlan dicts as returned by the LLM",
    )

    usage: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        comment="Aggregated LLM token/cost usage summary across all parallel planner calls",
    )

    # ── Audit ─────────────────────────────────────────────────────────────────
    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="UTC timestamp of row creation",
    )

    # ── Repr ─────────────────────────────────────────────────────────────────
    def __repr__(self) -> str:
        return (
            f"<FrontendPlan id={self.id!s} "
            f"extraction_id={self.extraction_id!r}>"
        )
