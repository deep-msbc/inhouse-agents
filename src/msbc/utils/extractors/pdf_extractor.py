"""
PDF text and heading extraction.

Backends (tried in order):
  1. pdfplumber  — better layout reconstruction, handles most PDFs.
  2. PyMuPDF     — faster fallback for files pdfplumber cannot parse.

Public API
----------
extract_text(file_bytes)              -> str
extract_heading_hierarchy(file_bytes) -> list[dict]
"""

import io
import logging
import re

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Public functions
# ─────────────────────────────────────────────────────────────────────────────

def extract_text(file_bytes: bytes) -> str:
    """
    Extract text from a PDF, trying pdfplumber then PyMuPDF.

    Returns:
        Cleaned plain text string.

    Raises:
        ValueError: If both backends fail or the PDF is image-only.
    """
    text = _extract_pdfplumber(file_bytes)
    if text and text.strip():
        return _clean_text(text)

    logger.warning("pdfplumber returned empty text; trying PyMuPDF fallback.")
    text = _extract_pymupdf(file_bytes)
    if text and text.strip():
        return _clean_text(text)

    raise ValueError(
        "Could not extract any text from the PDF. "
        "The file may be scanned/image-based. Please use a text-selectable PDF."
    )


def extract_heading_hierarchy(file_bytes: bytes) -> list[dict]:
    """
    Extract headings from a PDF using heuristic patterns on the raw text.

    Since PDF has no semantic style metadata (unlike DOCX), heuristics are
    the only reliable approach for plain-text PDFs.

    Returns:
        Ordered list of {"level": int, "text": str} dicts.
        Returns [] when no patterns match (caller handles gracefully).
    """
    text = extract_text(file_bytes)
    headings = _heuristic_headings(text)

    if not headings:
        logger.warning(
            "extract_heading_hierarchy: no headings detected in PDF. "
            "Segmentation LLM will receive raw text as context."
        )
    return headings


# ─────────────────────────────────────────────────────────────────────────────
# PDF backends
# ─────────────────────────────────────────────────────────────────────────────

def _extract_pdfplumber(file_bytes: bytes) -> str:
    try:
        import pdfplumber
    except ImportError:
        logger.warning("pdfplumber not installed. Run: pip install pdfplumber")
        return ""

    pages: list[str] = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                pages.append(page_text.strip())
    return "\n\n".join(pages)


def _extract_pymupdf(file_bytes: bytes) -> str:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.warning("PyMuPDF (fitz) not installed. Run: pip install pymupdf")
        return ""

    pages: list[str] = []
    with fitz.open(stream=file_bytes, filetype="pdf") as doc:
        for page in doc:
            pages.append(page.get_text())
    return "\n\n".join(pages)


# ─────────────────────────────────────────────────────────────────────────────
# Heuristic heading detector
# ─────────────────────────────────────────────────────────────────────────────

def _heuristic_headings(text: str) -> list[dict]:
    """
    Detect headings from plain PDF text using pattern matching.

    Detection rules (applied in priority order per line):
      1. Markdown headings     — # / ## / ### / ####
      2. Numbered sections     — "1. Title", "1.1 Title", "Chapter 2 …"
      3. RST underlined titles — next line is === or ---
      4. ALL-CAPS lines        — ≥10 chars, contains letters, not punctuation-only
      5. Short standalone lines followed by a blank line
    """
    lines = text.splitlines()
    headings: list[dict] = []
    n = len(lines)
    skip_next = False

    for i, line in enumerate(lines):
        if skip_next:
            skip_next = False
            continue

        stripped = line.strip()
        if not stripped:
            continue

        # 1. Markdown headings
        m = re.match(r"^(#{1,6})\s+(.+)", stripped)
        if m:
            headings.append({"level": len(m.group(1)), "text": m.group(2).strip()})
            continue

        # 2. Numbered sections
        if re.match(r"^\d+(\.|\d+)*\.?\s+[A-Z\u0080-\uFFFF]", stripped) or re.match(
            r"^(Chapter|Section|Part|Module)\s+\d+", stripped, re.IGNORECASE
        ):
            headings.append({"level": 2, "text": stripped})
            continue

        # 3. RST underlined titles
        if i + 1 < n:
            next_s = lines[i + 1].strip()
            if (
                next_s
                and re.match(r"^[=\-]{3,}$", next_s)
                and len(next_s) >= max(3, len(stripped) // 2)
            ):
                headings.append({"level": 1, "text": stripped})
                skip_next = True
                continue

        # 4. ALL-CAPS line
        if (
            len(stripped) >= 10
            and stripped.upper() == stripped
            and re.search(r"[A-Z]{3,}", stripped)
            and not re.fullmatch(r"[^a-zA-Z0-9]*", stripped)
        ):
            headings.append({"level": 1, "text": stripped})
            continue

        # 5. Short standalone line followed by a blank line
        if (
            2 <= len(stripped.split()) <= 12
            and len(stripped) <= 80
            and stripped[-1] not in (".", ",", ";", ":")
            and not re.search(r"\w\.\s+\w", stripped)
            and i + 1 < n
            and not lines[i + 1].strip()
        ):
            headings.append({"level": 2, "text": stripped})

    return headings


# ─────────────────────────────────────────────────────────────────────────────
# Text cleaning
# ─────────────────────────────────────────────────────────────────────────────

def _clean_text(text: str) -> str:
    """
    Normalize whitespace without removing any meaningful content.

    Steps:
    1. Strip null bytes and ASCII control chars (except tab/newline).
    2. Collapse runs of horizontal whitespace to one space per line.
    3. Strip trailing whitespace from every line.
    4. Collapse 3+ consecutive blank lines down to 2.
    """
    if not text:
        return text

    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = re.sub(r"[^\S\n]+", " ", text)
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()
