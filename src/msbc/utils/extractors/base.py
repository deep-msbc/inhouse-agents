"""
Text extraction dispatcher.

Routes to the correct extractor (DOCX or PDF) based on file extension,
falling back to content-type when extension is unrecognised.

Public API
----------
extract_text_from_file(file_bytes, filename, content_type) -> str
extract_heading_hierarchy(file_bytes, filename, content_type) -> list[dict]
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_text_from_file(
    file_bytes: bytes,
    filename: str,
    content_type: str,
) -> str:
    """
    Detect file type and extract plain text.

    Args:
        file_bytes:   Raw bytes of the uploaded file.
        filename:     Original filename (used to detect extension).
        content_type: MIME type reported by the client.

    Returns:
        Extracted plain text as a single string.

    Raises:
        ValueError: If the file type is not supported.
    """
    from src.msbc.utils.extractors.docx_extractor import (
        extract_text as _docx_text,
    )
    from src.msbc.utils.extractors.pdf_extractor import (
        extract_text as _pdf_text,
    )

    ext = Path(filename).suffix.lower()

    if ext == ".docx":
        logger.info("Extracting text from DOCX: %s", filename)
        return _docx_text(file_bytes)

    if ext == ".pdf":
        logger.info("Extracting text from PDF: %s", filename)
        return _pdf_text(file_bytes)

    # Extension not recognised — fall back to content-type (best-effort)
    if "wordprocessingml" in (content_type or ""):
        logger.info("Extracting DOCX text via content-type fallback: %s", filename)
        return _docx_text(file_bytes)

    if (content_type or "") == "application/pdf":
        logger.info("Extracting PDF text via content-type fallback: %s", filename)
        return _pdf_text(file_bytes)

    raise ValueError(
        f"Unsupported file type '{ext}'. Only .docx and .pdf are supported."
    )


def extract_heading_hierarchy(
    file_bytes: bytes,
    filename: str,
    content_type: str,
) -> list[dict]:
    """
    Extract the document's heading structure as an ordered list.

    For DOCX: uses python-docx paragraph styles (authoritative — no regex needed).
    For PDF:  uses heuristic regex patterns on extracted plain text.

    Returns:
        List of dicts: [{"level": int, "text": str}, ...]
        Level 0 = document Title style (DOCX only).
        Level 1-6 = Heading 1 through Heading 6.

    Raises:
        ValueError: If the file type is not supported.
    """
    from src.msbc.utils.extractors.docx_extractor import (
        extract_heading_hierarchy as _docx_headings,
    )
    from src.msbc.utils.extractors.pdf_extractor import (
        extract_heading_hierarchy as _pdf_headings,
    )

    ext = Path(filename).suffix.lower()

    if ext == ".docx" or "wordprocessingml" in (content_type or ""):
        logger.info("Extracting heading hierarchy from DOCX: %s", filename)
        return _docx_headings(file_bytes)

    if ext == ".pdf" or (content_type or "") == "application/pdf":
        logger.info("Extracting heading hierarchy from PDF: %s", filename)
        return _pdf_headings(file_bytes)

    raise ValueError(
        f"Unsupported file type '{ext}' for heading extraction."
    )
