"""
ORM entity: requirement_extractions table.

Each row represents one successful run of the Requirement Extractor agent.

Columns
-------
id                      UUID primary key (auto-generated)
user_story_id           Caller-supplied identifier for the uploaded user story
                        (e.g. file name, external ticket ID, or any opaque string).
mode                    Extraction mode: "frontend" | "backend" | "both"
extracted_requirements  Full structured output returned by the LLM (JSONB)
dependency_graph        Dependency graph (nodes/edges) produced by the graph builder (JSONB)
usage                   LLM token/cost usage summary (JSONB)
created_at              Row creation timestamp (UTC, auto-set by the DB)
"""

from __future__ import annotations

import uuid

from sqlalchemy import DateTime, JSON, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from src.msbc.database.base import Base


def _uuid_col():
    """Return a UUID column compatible with both PostgreSQL and SQLite."""
    if settings.DATABASE_URL.startswith("sqlite"):
        from sqlalchemy import String as _S
        return _S(36)
    from sqlalchemy.dialects.postgresql import UUID
    return UUID(as_uuid=True)


class RequirementExtraction(Base):
    """Persisted record for a single requirement-extraction run."""

    __tablename__ = "requirement_extractions"

    # ── Primary key ───────────────────────────────────────────────────────────
    id: Mapped[str] = mapped_column(
        _uuid_col(),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Unique run identifier",
    )

    # ── Extraction context ────────────────────────────────────────────────────
    user_story_id: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        index=True,
        comment="Caller-supplied user story identifier (filename, ticket ID, etc.)",
    )

    mode: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Extraction mode: frontend | backend | both",
    )

    # ── Payload ───────────────────────────────────────────────────────────────
    # JSON works on both SQLite and PostgreSQL (PostgreSQL also accepts JSONB;
    # switch back to JSONB dialect type when moving to Postgres permanently).
    extracted_requirements: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        comment="Full structured requirements JSON returned by the LLM",
    )

    dependency_graph: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        comment="Dependency graph (nodes/edges) produced by the graph builder node",
    )

    usage: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        comment="LLM token/cost usage summary (input_tokens, output_tokens, cost_usd, model)",
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
            f"<RequirementExtraction id={self.id!s} "
            f"user_story_id={self.user_story_id!r} mode={self.mode!r}>"
        )
