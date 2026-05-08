"""Standalone Python syntax validator using ast.parse()."""

import ast
import logging

logger = logging.getLogger(__name__)


def validate_syntax(code: str) -> tuple[bool, str]:
    """
    Parse *code* with ast.parse().

    Returns:
        (True, "")          on success
        (False, error_msg)  on SyntaxError
    """
    if not code or not code.strip():
        return False, "Empty code string"
    try:
        ast.parse(code)
        return True, ""
    except SyntaxError as exc:
        msg = f"SyntaxError at line {exc.lineno}: {exc.msg} — {exc.text!r}"
        logger.debug("validate_syntax: %s", msg)
        return False, msg
