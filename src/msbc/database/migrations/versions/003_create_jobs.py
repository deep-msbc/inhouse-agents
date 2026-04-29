"""create jobs table

Revision ID: 003_create_jobs
Revises: 002
Create Date: 2026-04-28

Creates the ``jobs`` table which tracks async job lifecycle for both
the Requirement Extractor and Frontend Planner endpoints.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column(
            "id",
            sa.String(36),
            primary_key=True,
            nullable=False,
            comment="Unique job identifier returned to the caller immediately",
        ),
        sa.Column(
            "job_type",
            sa.String(50),
            nullable=False,
            comment="requirement_extraction | frontend_planning",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
            comment="pending | processing | completed | failed",
        ),
        sa.Column(
            "result",
            sa.JSON,
            nullable=True,
            comment="Full result payload — populated when status = completed",
        ),
        sa.Column(
            "error_message",
            sa.Text,
            nullable=True,
            comment="Error description — populated when status = failed",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="UTC timestamp of job creation",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="UTC timestamp of last status change",
        ),
    )
    op.create_index("ix_jobs_job_type", "jobs", ["job_type"])
    op.create_index("ix_jobs_status", "jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_index("ix_jobs_job_type", table_name="jobs")
    op.drop_table("jobs")
