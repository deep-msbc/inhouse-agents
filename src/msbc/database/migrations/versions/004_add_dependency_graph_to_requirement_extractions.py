"""add dependency_graph to requirement_extractions

Revision ID: 004
Revises: a1b2c3d4e5f6
Create Date: 2026-05-06

Migration 001 created the requirement_extractions table without the
dependency_graph column.  The ORM entity always had it, causing every
INSERT to fail with "column does not exist" and silently leaving the
table empty.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "004"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "requirement_extractions",
        sa.Column(
            "dependency_graph",
            JSONB,
            nullable=True,
            comment="Dependency graph (nodes/edges) produced by the graph builder node",
        ),
    )


def downgrade() -> None:
    op.drop_column("requirement_extractions", "dependency_graph")
