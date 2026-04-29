"""
Generic CRUD base repository.

Concrete repositories inherit from ``BaseRepository[T]`` and get standard
create / get / list / delete operations for free.  More specialised queries
are added in the concrete subclass.
"""

from __future__ import annotations

from typing import Generic, Type, TypeVar
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.msbc.database.base import Base

T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    """Generic repository providing common CRUD operations."""

    def __init__(self, model: Type[T], db: Session) -> None:
        self._model = model
        self._db = db

    # ── Create ────────────────────────────────────────────────────────────────

    def create(self, instance: T) -> T:
        """Persist a new entity and flush so the DB-generated fields are populated."""
        self._db.add(instance)
        self._db.flush()          # sends INSERT; commit happens in get_db context
        self._db.refresh(instance)
        return instance

    # ── Read ──────────────────────────────────────────────────────────────────

    def get_by_id(self, record_id: UUID) -> T | None:
        """Return the entity with the given UUID, or ``None`` if not found."""
        return self._db.get(self._model, record_id)

    def list_all(self, *, limit: int = 100, offset: int = 0) -> list[T]:
        """Return a paginated list of all entities (newest-first by default)."""
        stmt = select(self._model).offset(offset).limit(limit)
        return list(self._db.scalars(stmt).all())

    # ── Delete ────────────────────────────────────────────────────────────────

    def delete(self, instance: T) -> None:
        """Delete an entity from the database."""
        self._db.delete(instance)
        self._db.flush()
