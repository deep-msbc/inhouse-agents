"""
Extractor sub-package.

Exports:
    extract_text_from_file       — full plain-text extraction (str)
    extract_heading_hierarchy    — structured headings ([{level, text}])
"""

from src.msbc.utils.extractors.base import (
    extract_heading_hierarchy,
    extract_text_from_file,
)

__all__ = ["extract_text_from_file", "extract_heading_hierarchy"]
