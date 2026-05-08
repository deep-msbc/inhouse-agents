"""
src/msbc/llm/prompts/loader.py
──────────────────────────────
Shared YAML prompt loader.

Usage:
    from src.msbc.llm.prompts.loader import load_prompt

    prompt = load_prompt("code_generator/rerank_chunks.yaml")
    system = prompt.system
    user   = prompt._fmt(prompt.user_template, key=value, ...)

Rules (from CLAUDE.md §17):
  - Always use _fmt() — never .format() — so JSON examples inside YAML
    (e.g. {"key": 1}) are never mistaken for Python format placeholders.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_TEMPLATES_DIR = Path(__file__).parent / "templates"


class _Prompt:
    """Wrapper around a loaded YAML prompt file."""

    def __init__(self, data: dict) -> None:
        self.system: str = data.get("system", "")
        self.user_template: str = data.get("user_template", "")
        self._data = data

    def _fmt(self, template: str, **kwargs: str) -> str:
        """
        Safe template substitution using plain str.replace().

        Unlike str.format(), this never raises KeyError on literal braces
        that appear in JSON examples embedded inside YAML prompts.
        """
        result = template
        for key, value in kwargs.items():
            result = result.replace(f"{{{key}}}", value)
        return result

    def get(self, key: str, default=None):
        """Dict-style access to raw YAML keys."""
        return self._data.get(key, default)


def load_prompt(path: str) -> _Prompt:
    """
    Load a YAML prompt file relative to the templates/ directory.

    Parameters
    ----------
    path : str
        Path relative to ``templates/``, e.g.
        ``"code_generator/rerank_chunks.yaml"`` or
        ``"requirement_extractor/base_rules.yaml"``.

    Returns
    -------
    _Prompt
        Object with ``.system``, ``.user_template``, and ``._fmt()`` method.
    """
    full_path = _TEMPLATES_DIR / path
    with full_path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return _Prompt(data or {})
