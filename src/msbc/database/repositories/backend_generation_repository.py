"""Repository for BackendGeneration records."""

from __future__ import annotations

from sqlalchemy.orm import Session

from src.msbc.database.repositories.base_repository import BaseRepository
from src.msbc.models.entities.backend_generation import BackendGeneration


class BackendGenerationRepository(BaseRepository[BackendGeneration]):
    """CRUD for the backend_generations table. Inherits create() + get_by_id()."""

    def __init__(self, db: Session) -> None:
        super().__init__(BackendGeneration, db)
