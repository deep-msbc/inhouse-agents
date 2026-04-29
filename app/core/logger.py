"""
Centralised logging setup.

All modules obtain a logger via get_logger(__name__).
Log level is controlled by the LOG_LEVEL env var (default: INFO).
Format includes timestamp, level, module name, and message.
"""

import logging
import sys

from app.core.config import settings


def _configure_root_logger() -> None:
    """Configure the root logger once at import time."""
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(handler)
    root.setLevel(level)

    # Silence noisy third-party loggers
    for noisy in ("httpx", "httpcore", "openai", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


_configure_root_logger()


def get_logger(name: str) -> logging.Logger:
    """Return a named logger inheriting the root configuration."""
    return logging.getLogger(name)
