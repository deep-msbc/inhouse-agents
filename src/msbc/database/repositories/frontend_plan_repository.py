"""
Repository for ``FrontendPlan`` records.

All database access for the ``frontend_plans`` table is centralised here.
The orchestration graph and API router call these methods — they must never
write raw SQLAlchemy queries outside this class.

Usage::

    from sqlalchemy.orm import Session
    from src.msbc.database.repositories import FrontendPlanRepository

    def save(db: Session, extraction_id: str, plan: list, usage: dict):
        repo = FrontendPlanRepository(db)
        return repo.save_plan(extraction_id=extraction_id, plan=plan, usage=usage)
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.msbc.database.repositories.base_repository import BaseRepository
from src.msbc.models.entities.frontend_plan import FrontendPlan


class FrontendPlanRepository(BaseRepository[FrontendPlan]):
    """CRUD + domain queries for the ``frontend_plans`` table."""

    def __init__(self, db: Session) -> None:
        super().__init__(FrontendPlan, db)

    # ── Write ─────────────────────────────────────────────────────────────────

    def save_plan(
        self,
        *,
        extraction_id: str,
        plan: list[dict[str, Any]],
        usage: dict[str, Any],
    ) -> FrontendPlan:
        """
        Persist a new frontend plan run and return the saved entity.

        Parameters
        ----------
        extraction_id:
            UUID string referencing the source ``requirement_extractions`` row.
        plan:
            List of ModulePlan dicts as returned by the LLM (serialised from
            ``PlannerOutput.modules`` via ``model.model_dump()``).
        usage:
            Aggregated token/cost summary dict (``PlannerLLMUsage.model_dump()``).

        Returns
        -------
        FrontendPlan
            The freshly inserted row with ``id`` and ``created_at`` populated.
        """
        record = FrontendPlan(
            extraction_id=extraction_id,
            plan=plan,
            usage=usage,
        )
        return self.create(record)

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_by_plan_id(self, plan_id: str) -> FrontendPlan | None:
        """Fetch a single plan by its UUID string."""
        return self._db.get(FrontendPlan, plan_id)

    def list_by_extraction(
        self,
        extraction_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[FrontendPlan]:
        """
        Return all plan runs derived from a given extraction, newest-first.

        An extraction can have multiple plan runs (e.g. re-runs with different
        settings), so this method returns all of them ordered newest-first.
        """
        stmt = (
            select(FrontendPlan)
            .where(FrontendPlan.extraction_id == extraction_id)
            .order_by(FrontendPlan.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self._db.scalars(stmt).all())

    def get_latest_for_extraction(self, extraction_id: str) -> FrontendPlan | None:
        """Return the most recent plan for a given extraction, or None."""
        stmt = (
            select(FrontendPlan)
            .where(FrontendPlan.extraction_id == extraction_id)
            .order_by(FrontendPlan.created_at.desc())
            .limit(1)
        )
        return self._db.scalars(stmt).first()
