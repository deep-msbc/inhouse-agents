"""
ORM entity: backend_generations table.

Each row represents one run of the Stage 3 Backend Code Generation pipeline.

Columns
-------
id              UUID primary key (auto-generated)
extraction_id   FK → requirement_extractions.id (string, indexed, not nullable)
project_name    Name of the generated Django project (not nullable)
output_path     Absolute path on disk where the project was written (not nullable)
cli_stdout      Raw stdout captured from the djcli subprocess (nullable)
cli_stderr      Raw stderr captured from the djcli subprocess (nullable)
pipeline_output Full PipelineOutput JSON returned by the Stage 3 pipeline (nullable)
success         True if the full pipeline (CLI + all codegen) succeeded (not nullable)
created_at      Row creation timestamp (UTC, auto-set by the DB)
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from src.msbc.database.base import Base


def _uuid_col():
    """Always store UUIDs as VARCHAR(36) — matches the VARCHAR column in migrations."""
    return String(36)


class BackendGeneration(Base):
    """Persisted record for a single Stage 3 backend code generation run."""

    __tablename__ = "backend_generations"

    # ── Primary key ───────────────────────────────────────────────────────────
    id: Mapped[str] = mapped_column(
        _uuid_col(),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Unique generation run identifier",
    )

    # ── Lineage ───────────────────────────────────────────────────────────────
    extraction_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("requirement_extractions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="FK to the requirement_extractions row that triggered this run",
    )

    # ── Project identity ──────────────────────────────────────────────────────
    project_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Name of the generated Django project (sanitised snake_case)",
    )

    output_path: Mapped[str] = mapped_column(
        String(1024),
        nullable=False,
        comment="Absolute path on disk where djcli wrote the project",
    )

    # ── Subprocess capture ────────────────────────────────────────────────────
    cli_stdout: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Raw stdout from the djcli subprocess invocation",
    )

    cli_stderr: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Raw stderr from the djcli subprocess invocation",
    )

    # ── Pipeline result ───────────────────────────────────────────────────────
    pipeline_output: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        comment="Full PipelineOutput JSON (generated_apps, generated_files, errors, etc.)",
    )

    # ── Status ────────────────────────────────────────────────────────────────
    success: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        comment="True if CLI + all codegen steps completed without errors",
    )

    # ── Audit ─────────────────────────────────────────────────────────────────
    created_at: Mapped[str] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="UTC timestamp of row creation",
    )

    # ── Repr ──────────────────────────────────────────────────────────────────
    def __repr__(self) -> str:
        return (
            f"<BackendGeneration id={self.id!s} "
            f"project={self.project_name!r} success={self.success!r}>"
        )