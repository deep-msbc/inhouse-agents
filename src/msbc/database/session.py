"""
Database session management.

Provides ``get_db`` — a FastAPI dependency that yields a transactional
``Session`` and closes it after the request completes (or rolls back on error).
"""

from collections.abc import Generator

from sqlalchemy.orm import Session

from src.msbc.database.base import engine


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that provides a SQLAlchemy ``Session``.

    Usage::

        @router.post("/")
        def my_endpoint(db: Session = Depends(get_db)):
            ...
    """
    with Session(engine) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
