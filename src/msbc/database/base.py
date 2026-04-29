"""
SQLAlchemy engine and declarative Base.

All ORM models must import ``Base`` from here so that Alembic's
``target_metadata`` covers every table in a single pass.

Engine settings are driven by ``app.core.config.settings`` so that
DATABASE_URL (and pool tunables) come from the environment / .env file.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    """Project-wide declarative base — all ORM models inherit from this."""


_is_sqlite = settings.DATABASE_URL.startswith("sqlite")

# SQLite does not support pool_size / max_overflow / pool_pre_ping
_engine_kwargs: dict = {"echo": settings.DATABASE_ECHO}
if not _is_sqlite:
    _engine_kwargs.update(
        pool_size=settings.DATABASE_POOL_SIZE,
        max_overflow=settings.DATABASE_MAX_OVERFLOW,
        pool_pre_ping=True,
    )

engine = create_engine(settings.DATABASE_URL, **_engine_kwargs)
