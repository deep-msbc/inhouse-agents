"""
Request validation for the requirement extractor endpoint.

Validates:
  - Uploaded file: presence, extension, content-type
  - File size: enforces MAX_FILE_SIZE_BYTES
  - Extraction mode: must be one of frontend | backend | both

Raises FastAPI HTTPException so the router receives clean, validated inputs.
Messages are sourced from app.core.helpers.message for consistency.
"""

import logging
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from app.core.helpers.message import FILE_ERRORS, MODE_ERRORS
from src.msbc.config import (
    ALLOWED_CONTENT_TYPES,
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE_BYTES,
    VALID_MODES,
)

logger = logging.getLogger(__name__)


def validate_uploaded_file(file: UploadFile) -> None:
    """
    Validate the uploaded file for presence, extension, and content-type.

    Raises:
        HTTPException 400 on validation failure.
    """
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=FILE_ERRORS["no_filename"],
        )

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                FILE_ERRORS["unsupported_type"].format(
                    allowed=", ".join(sorted(ALLOWED_EXTENSIONS))
                )
                + f" Received: '{ext}'"
            ),
        )

    # Content-type is lenient — some browsers send generic types for valid files.
    content_type = (file.content_type or "").lower()
    if content_type and content_type not in ALLOWED_CONTENT_TYPES:
        logger.warning(
            FILE_ERRORS["unexpected_content_type"].format(
                content_type=content_type, filename=file.filename
            )
        )


def validate_file_size(file_bytes: bytes) -> None:
    """
    Enforce the maximum file size limit.

    Raises:
        HTTPException 413 if the file exceeds MAX_FILE_SIZE_BYTES.
    """
    size = len(file_bytes)
    if size > MAX_FILE_SIZE_BYTES:
        limit_mb = MAX_FILE_SIZE_BYTES // (1024 * 1024)
        actual_mb = size / (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=FILE_ERRORS["file_too_large"].format(
                actual_mb=actual_mb, limit_mb=limit_mb
            ),
        )


def validate_mode(mode: str) -> None:
    """
    Validate the extraction mode parameter.

    Raises:
        HTTPException 400 if mode is not one of: frontend, backend, both.
    """
    if mode not in VALID_MODES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=MODE_ERRORS["invalid_mode"].format(
                mode=mode, allowed=", ".join(sorted(VALID_MODES))
            ),
        )
