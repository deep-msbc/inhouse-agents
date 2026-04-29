"""
Alembic environment configuration.

Runs in two modes:
  * ``offline``  — generates SQL scripts without a live DB connection.
  * ``online``   — applies migrations against the live PostgreSQL instance.

The ``target_metadata`` is built by importing all ORM entity models so that
Alembic can detect schema changes automatically with ``alembic revision --autogenerate``.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# ── Load the shared app config to pull DATABASE_URL ──────────────────────────
from app.core.config import settings

# ── Import Base *after* all entity models so metadata is fully populated ─────
from src.msbc.database.base import Base  # noqa: F401 — triggers engine creation
import src.msbc.models.entities  # noqa: F401 — registers all ORM classes with Base

# Alembic Config object (gives access to values in alembic.ini)
config = context.config

# Wire up Python logging from the ini file (optional but useful)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The metadata Alembic will compare against when auto-generating revisions
target_metadata = Base.metadata

# Override the sqlalchemy.url from alembic.ini with the app's setting
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)


# ── Offline mode ─────────────────────────────────────────────────────────────

def run_migrations_offline() -> None:
    """
    Emit migrations as SQL to stdout (no DB connection required).

    Useful for generating review scripts or deploying via CI without a live DB.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online mode ───────────────────────────────────────────────────────────────

def run_migrations_online() -> None:
    """
    Apply migrations against a live DB connection.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


# ── Entry point ───────────────────────────────────────────────────────────────

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
