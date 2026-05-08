"""
Application configuration.

All environment variables are loaded via pydantic-settings (BaseSettings).
Override any value by setting the matching env var or adding it to .env.

Install: pip install pydantic-settings
"""

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── Application ───────────────────────────────────────────────────────────
    PROJECT_NAME: str = "DevAgents"
    VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"      # development | staging | production
    DEBUG: bool = True

    # ── API ───────────────────────────────────────────────────────────────────
    API_V1_PREFIX: str = "/api/v1"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    RELOAD: bool = True
    CORS_ORIGINS: List[str] = ["*"]

    # ── LLM ───────────────────────────────────────────────────────────────────
    OPENAI_API_KEY: str = ""
    LLM_MODEL: str = "gpt-4.1-mini"
    LLM_TIMEOUT: int = 300              # seconds per individual LLM call

    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/devagents"
    DATABASE_ECHO: bool = False          # set True in dev to log SQL statements
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 5

    # ── Logging ───────────────────────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"

    # ── Qdrant ────────────────────────────────────────────────────────────────
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str = ""

    # ── Embedding ─────────────────────────────────────────────────────────────
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-large"
    EMBEDDING_DIMENSIONS: int = 1536

    # ── Toolkit & Examples Paths ──────────────────────────────────────────────
    RTK_MONOREPO_PATH: str = ""
    EXAMPLES_DIR: str = "correct_code_examples"

    # ── KUZU Graph DB ─────────────────────────────────────────────────────────
    KUZU_DB_PATH: str = "./data/toolkit_graph.kuzu"

    # ── Code Generator ────────────────────────────────────────────────────────
    CODEGEN_OUTPUT_ROOT: str = "./generated_frontend"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,
        case_sensitive=True,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()
