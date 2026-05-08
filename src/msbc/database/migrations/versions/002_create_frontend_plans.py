"""create frontend_plans table

Revision ID: 002_create_frontend_plans
Revises: 001
Create Date: 2026-04-27

Creates the ``frontend_plans`` table which stores one row per Frontend
Planner Agent run.  Each plan is linked back to the source extraction via
a FK → requirement_extractions.id.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers
revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "frontend_plans",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
            comment="Unique plan identifier",
        ),
        sa.Column(
            "extraction_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "requirement_extractions.id",
                ondelete="CASCADE",
                name="fk_frontend_plans_extraction_id",
            ),
            nullable=False,
            comment="FK → requirement_extractions.id",
        ),
        sa.Column(
            "plan",
            JSONB,
            nullable=False,
            comment="Full structured plan — array of ModulePlan dicts",
        ),
        sa.Column(
            "usage",
            JSONB,
            nullable=False,
            comment="Aggregated LLM token/cost usage summary",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
            comment="UTC timestamp of row creation",
        ),
    )

    # Index for efficient look-ups by extraction (most common query pattern)
    op.create_index(
        "ix_frontend_plans_extraction_id",
        "frontend_plans",
        ["extraction_id"],
    )

    # Composite index for "latest plan per extraction" pattern
    op.create_index(
        "ix_frontend_plans_extraction_created",
        "frontend_plans",
        ["extraction_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_frontend_plans_extraction_created", table_name="frontend_plans")
    op.drop_index("ix_frontend_plans_extraction_id", table_name="frontend_plans")
    op.drop_table("frontend_plans")
