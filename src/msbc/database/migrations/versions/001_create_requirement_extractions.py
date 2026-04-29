"""create requirement_extractions table

Revision ID: 001_create_requirement_extractions
Revises:
Create Date: 2026-04-27

Creates the initial ``requirement_extractions`` table which stores one row
per Requirement Extractor agent run.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "requirement_extractions",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
            comment="Unique run identifier",
        ),
        sa.Column(
            "user_story_id",
            sa.String(512),
            nullable=False,
            comment="Caller-supplied user story identifier (filename, ticket ID, etc.)",
        ),
        sa.Column(
            "mode",
            sa.String(20),
            nullable=False,
            comment="Extraction mode: frontend | backend | both",
        ),
        sa.Column(
            "extracted_requirements",
            JSONB,
            nullable=False,
            comment="Full structured requirements JSON returned by the LLM",
        ),
        sa.Column(
            "usage",
            JSONB,
            nullable=False,
            comment="LLM token/cost usage summary",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
            comment="UTC timestamp of row creation",
        ),
    )

    # Index for efficient look-ups by user story
    op.create_index(
        "ix_requirement_extractions_user_story_id",
        "requirement_extractions",
        ["user_story_id"],
    )

    # Index for filtering by mode
    op.create_index(
        "ix_requirement_extractions_mode",
        "requirement_extractions",
        ["mode"],
    )


def downgrade() -> None:
    op.drop_index("ix_requirement_extractions_mode", table_name="requirement_extractions")
    op.drop_index("ix_requirement_extractions_user_story_id", table_name="requirement_extractions")
    op.drop_table("requirement_extractions")
