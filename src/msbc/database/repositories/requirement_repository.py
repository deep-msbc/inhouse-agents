"""
Repository for ``RequirementExtraction`` records.

All database access for the ``requirement_extractions`` table is centralised
here.  The router (or service layer) should call these methods; it must never
write raw SQLAlchemy queries outside this class.

Usage::

    from sqlalchemy.orm import Session
    from src.msbc.database.repositories import RequirementRepository
    from src.msbc.models.entities import RequirementExtraction

    def save(db: Session, **kwargs) -> RequirementExtraction:
        repo = RequirementRepository(db)
        return repo.save_extraction(**kwargs)
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.msbc.database.repositories.base_repository import BaseRepository
from src.msbc.models.entities.requirement_extraction import RequirementExtraction


class RequirementRepository(BaseRepository[RequirementExtraction]):
    """CRUD + domain queries for the ``requirement_extractions`` table."""

    def __init__(self, db: Session) -> None:
        super().__init__(RequirementExtraction, db)

    # ── Write ─────────────────────────────────────────────────────────────────

    def save_extraction(
        self,
        *,
        user_story_id: str,
        mode: str,
        extracted_requirements: dict[str, Any],
        dependency_graph: dict[str, Any] | None = None,
        usage: dict[str, Any],
    ) -> RequirementExtraction:
        """
        Persist a new extraction run and return the saved entity.

        Parameters
        ----------
        user_story_id:
            Caller-supplied identifier for the uploaded user story
            (e.g. original filename or an external ticket ID).
        mode:
            Extraction mode — one of ``"frontend"``, ``"backend"``, ``"both"``.
        extracted_requirements:
            Full structured requirements dict as returned by the LLM.
        dependency_graph:
            Dependency graph (nodes/edges) produced by the graph builder node.
        usage:
            Token/cost summary dict (``LLMUsage.model_dump()``).

        Returns
        -------
        RequirementExtraction
            The freshly inserted row with ``id`` and ``created_at`` populated.
        """
        record = RequirementExtraction(
            user_story_id=user_story_id,
            mode=mode,
            extracted_requirements=extracted_requirements,
            dependency_graph=dependency_graph,
            usage=usage,
        )
        return self.create(record)

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_by_run_id(self, run_id: uuid.UUID | str) -> RequirementExtraction | None:
        """Fetch a single extraction run by its UUID."""
        return self.get_by_id(str(run_id))

    def list_by_user_story(
        self,
        user_story_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[RequirementExtraction]:
        """
        Return all extraction runs for a given ``user_story_id``,
        ordered newest-first.
        """
        stmt = (
            select(RequirementExtraction)
            .where(RequirementExtraction.user_story_id == user_story_id)
            .order_by(RequirementExtraction.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self._db.scalars(stmt).all())

    def list_by_mode(
        self,
        mode: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[RequirementExtraction]:
        """Return all extraction runs for a given ``mode``, newest-first."""
        stmt = (
            select(RequirementExtraction)
            .where(RequirementExtraction.mode == mode)
            .order_by(RequirementExtraction.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(self._db.scalars(stmt).all())
