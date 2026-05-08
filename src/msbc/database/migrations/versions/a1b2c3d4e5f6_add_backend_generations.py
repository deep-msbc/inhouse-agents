"""add_backend_generations

Revision ID: a1b2c3d4e5f6
Revises: <replace_with_latest_head>
Create Date: 2026-05-05

Adds the backend_generations table for Stage 3 pipeline run records.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "backend_generations",
        sa.Column(
            "id",
            sa.String(36),
            primary_key=True,
            nullable=False,
            comment="Unique generation run identifier",
        ),
        sa.Column(
            "extraction_id",
            UUID(as_uuid=True),
            sa.ForeignKey("requirement_extractions.id", ondelete="CASCADE"),
            nullable=False,
            comment="FK to the requirement_extractions row that triggered this run",
        ),
        sa.Column(
            "project_name",
            sa.String(255),
            nullable=False,
            comment="Name of the generated Django project (sanitised snake_case)",
        ),
        sa.Column(
            "output_path",
            sa.String(1024),
            nullable=False,
            comment="Absolute path on disk where djcli wrote the project",
        ),
        sa.Column(
            "cli_stdout",
            sa.Text,
            nullable=True,
            comment="Raw stdout from the djcli subprocess invocation",
        ),
        sa.Column(
            "cli_stderr",
            sa.Text,
            nullable=True,
            comment="Raw stderr from the djcli subprocess invocation",
        ),
        sa.Column(
            "pipeline_output",
            sa.JSON,
            nullable=True,
            comment="Full PipelineOutput JSON",
        ),
        sa.Column(
            "success",
            sa.Boolean,
            nullable=False,
            comment="True if CLI + all codegen steps completed without errors",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
            comment="UTC timestamp of row creation",
        ),
    )
    op.create_index(
        "ix_backend_generations_extraction_id",
        "backend_generations",
        ["extraction_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_backend_generations_extraction_id", table_name="backend_generations")
    op.drop_table("backend_generations")