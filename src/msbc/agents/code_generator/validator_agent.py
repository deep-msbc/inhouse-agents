"""
agents/code_generator/validator_agent.py
─────────────────────────────────────────
Phase 4 — Validator Agent.

Separate flat LangGraph that validates every generated file against Python
rule checks and repairs failures using an LLM fixer with max 2 retries.

Graph topology:
  START → validate_file → decide_retry → advance_validator → END
                               ↓ (errors AND retries remain)
                         regenerate_file
                               ↓
                         validate_file  (loop back)

Entry point: run_validation(generated_files, plan_modules, output_dir)
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from src.msbc.agents.code_generator.state import ValidatorState
from src.msbc.llm.clients.openai_client import call_llm_with_schema
from src.msbc.llm.prompts.loader import load_prompt

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_RETRIES = 2

ALLOWED_PACKAGES: set[str] = {
    "@msbc/config-ui",
    "@msbc/react-toolkit",
    "@msbc/data-layer",
    "@msbc/utils",
    "react",
    "react-hook-form",
}

_FIX_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["code"],
    "properties": {
        "code": {"type": "string"},
    },
    "additionalProperties": False,
}

# ---------------------------------------------------------------------------
# Pure-Python rule checks — no LLM
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Regex patterns for deterministic content checks
# ---------------------------------------------------------------------------

# Forbidden field type aliases (inside JS/TS string literals).
# These are wrong for JSONFormSchema field.type regardless of context.
_FORBIDDEN_FIELD_TYPES: list[tuple[str, str]] = [
    (r"type\s*:\s*(?:'|\")dropdown(?:'|\")", "Forbidden field type alias 'dropdown' \u2014 use 'select'"),
    (r"type\s*:\s*(?:'|\")toggle(?:'|\")",   "Forbidden field type alias 'toggle' \u2014 use 'checkbox'"),
    (r"type\s*:\s*(?:'|\")phone(?:'|\")",    "Forbidden field type alias 'phone' \u2014 use 'tel'"),
    (r"type\s*:\s*(?:'|\")multi_select(?:'|\")", "Forbidden field type alias 'multi_select' \u2014 use 'select'"),
    (r"type\s*:\s*(?:'|\")integer(?:'|\")",  "Forbidden field type alias 'integer' \u2014 use 'number'"),
    (r"type\s*:\s*(?:'|\")date_range(?:'|\")", "Forbidden field type alias 'date_range' \u2014 use 'date-range'"),
    (r"type\s*:\s*(?:'|\")boolean(?:'|\")",  "Forbidden field type alias 'boolean' \u2014 use 'bool' (filters) or 'checkbox' (fields)"),
    (r"type\s*:\s*(?:'|\")input(?:'|\")",    "Forbidden field type alias 'input' \u2014 use 'text'"),
]

# Forbidden API method casing (must be lowercase).
_UPPERCASE_METHOD_RE = re.compile(
    r"method\s*:\s*(?:'|\")(?:GET|POST|PUT|PATCH|DELETE)(?:'|\")"
)

# Forbidden raw HTML interactive elements.
_RAW_BUTTON_RE   = re.compile(r"<button[\s>/]", re.IGNORECASE)
_RAW_ANCHOR_RE   = re.compile(r"<a\s[^>]*href", re.IGNORECASE)
_DIV_ONCLICK_RE  = re.compile(r"<div[^>]+onClick", re.IGNORECASE)

# Inline style simulating a button.
_INLINE_STYLE_RE = re.compile(r"style\s*=\s*\{\{")

# Console.log (not inside a comment line).
_CONSOLE_LOG_RE = re.compile(r"console\.log\s*\(")

# Forbidden column-def keys that should be 'field' or 'headerName'.
# These patterns are deliberately tight to minimise false positives:
#   - preceded by whitespace or start-of-line (object property position)
#   - NOT preceded by a word char (avoids matching inside identifiers)
#   - followed by a colon and a string value
# They are only applied when a columnDefs block is detected in the file,
# and only against the extracted columnDefs block (see Check 7 below).
_FORBIDDEN_COL_KEYS: list[tuple[str, str]] = [
    (r"(?:^|[\s{,])name\s*:\s*(?:'|\")",   "Possible forbidden column key 'name' \u2014 use 'field'"),
    (r"(?:^|[\s{,])key\s*:\s*(?:'|\")",    "Possible forbidden column key 'key' \u2014 use 'field'"),
    (r"(?:^|[\s{,])title\s*:\s*(?:'|\")",  "Possible forbidden column key 'title' \u2014 use 'headerName'"),
]

# Forbidden ConfigurableForm props that don't exist in ConfigurableFormProps.
_FORBIDDEN_FORM_PROPS: list[tuple[str, str]] = [
    (r"\bschema\s*=\s*\{",        "ConfigurableForm prop 'schema=' does not exist \u2014 use 'config='"),
    (r"\bformData\s*=\s*\{",      "ConfigurableForm prop 'formData=' does not exist \u2014 remove it"),
    (r"\breadOnly\b(?:\s*=|\s*/>|\s*\n)", "ConfigurableForm prop 'readOnly' does not exist"),
    (r"\binitialValues\s*=\s*\{", "ConfigurableForm prop 'initialValues=' does not exist \u2014 use 'defaultValues='"),
    (r"\bserverError\s*=\s*\{",   "ConfigurableForm prop 'serverError=' does not exist \u2014 use 'error='"),
    (r"\bsubmitButtonText\s*=\s*", "ConfigurableForm prop 'submitButtonText=' does not exist \u2014 use 'primaryButtonProps={{ text: ... }}'"),
    (r"\bonCancel\s*=\s*\{",      "ConfigurableForm prop 'onCancel=' does not exist"),
    (r"\bcontrol\s*=\s*\{",       "ConfigurableForm prop 'control=' does not exist (form manages its own state)"),
    (r"\berrors\s*=\s*\{",        "ConfigurableForm prop 'errors=' does not exist"),
    (r"\bactions\s*=\s*\{",       "ConfigurableForm prop 'actions=' does not exist (actions belong in JSONFormSchema config)"),
]

# Forbidden ConfigurableDashboardHandle methods that don't exist.
_FORBIDDEN_HANDLE_METHODS: list[tuple[str, str]] = [
    (r"\.current\??\.\s*refresh\s*\(",           "dashboardRef.refresh() does not exist \u2014 use handleRefresh()"),
    (r"\.current\??\.\s*setFilter\s*\(",          "dashboardRef.setFilter() does not exist on ConfigurableDashboardHandle"),
    (r"\.current\??\.\s*setSearch\s*\(",          "dashboardRef.setSearch() does not exist on ConfigurableDashboardHandle"),
    (r"\.current\??\.\s*search\s*\(",             "dashboardRef.search() does not exist on ConfigurableDashboardHandle"),
    (r"\.current\??\.\s*setFilterValue\s*\(",     "dashboardRef.setFilterValue() does not exist on ConfigurableDashboardHandle"),
]

# Forbidden useApiRequest destructure keys.
_FORBIDDEN_APIREQUEST_KEYS_RE = re.compile(
    r"const\s*\{[^}]*\b(?:(?<!api)error|reset|isLoading|mutateAsync)\b[^}]*\}\s*=\s*use[A-Z]"
)

# Default import used where a named export is expected.
_DEFAULT_IMPORT_RE = re.compile(
    r"import\s+(?!\s*\{)(?!\s*\*)(?!\s*type\s*\{)\w+\s+from\s+['\"][./]"
)

# Inline interface definition in a non-types file (heuristic).
_INLINE_INTERFACE_RE = re.compile(
    r"^(?:export\s+)?interface\s+\w+\s*\{",
    re.MULTILINE,
)

# ConfigurableFormHandle \u2014 does not exist; catch useRef<ConfigurableFormHandle>.
_FORM_HANDLE_REF_RE = re.compile(r"useRef\s*<\s*ConfigurableFormHandle\s*>")

# Forbidden root-level DashboardConfig properties.
_FORBIDDEN_DASHBOARD_ROOT_KEYS: list[tuple[str, str]] = [
    (r"(?:^|\s)pagination\s*:", "DashboardConfig 'pagination:' is not a valid top-level property"),
    (r"(?:^|\s)pageSize\s*:",   "DashboardConfig 'pageSize:' is not a valid top-level property"),
    (r"(?:^|\s)rowActions\s*:", "DashboardConfig 'rowActions:' is not a valid top-level property"),
]

# columnDefs at root of DashboardConfig (not under tableProps).
# Heuristic: "columnDefs" appears before "tableProps" in the file, inside a const block.
_ROOT_COLUMNDEFS_RE = re.compile(r"(?:DashboardConfig)[^{]*\{[^}]*columnDefs\s*:", re.DOTALL)

# JSONFormSchema root-level forbidden keys.
_FORBIDDEN_SCHEMA_ROOT_KEYS: list[tuple[str, str]] = [
    (r"(?:^|\s)actions\s*:\s*\[",    "JSONFormSchema 'actions:' at root is not valid (pass buttons via ConfigurableForm props)"),
    (r"(?:^|\s)validations\s*:\s*\[","JSONFormSchema 'validations:' at root is not valid (use ConfigurableForm customValidators)"),
]

# Filter using 'key' instead of 'name'.
_FILTER_KEY_RE = re.compile(r"filters\s*:[^]]*\bkey\s*:\s*(?:'|\")", re.DOTALL)


def _is_code_line(line: str) -> bool:
    """Return True if the line is not a pure comment."""
    stripped = line.strip()
    return not (stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("/*"))


def _run_checks(file: dict, screen_plan: dict) -> list[str]:
    """
    Run deterministic rule checks on a generated file dict.

    Returns a list of error strings.  An empty list means all checks passed.
    """
    errors: list[str] = []
    content: str = file.get("content", "")
    file_type: str = file.get("file_type", "")
    lines = content.splitlines()
    code_lines = [l for l in lines if _is_code_line(l)]
    code_only = "\n".join(code_lines)

    # ── Check 1: Forbidden imports (packages outside the allowed set) ─────────
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("import") or "from" not in stripped:
            continue
        # Extract the module path from  import { ... } from '<pkg>'
        pkg = stripped.split("from")[-1].strip().strip("'\"`;")
        # Root package: first two segments for scoped (@msbc/foo), else first
        if pkg.startswith("@"):
            root = "/".join(pkg.split("/")[:2])
        else:
            root = pkg.split("/")[0]
        # Relative imports are fine; only check absolute packages
        if not root.startswith((".", "..")) and root not in ALLOWED_PACKAGES:
            errors.append(f"Forbidden import: {pkg}")

    # ── Check 2: No default exports ───────────────────────────────────────────
    if "export default" in content:
        errors.append("Default export found. Use named export only.")

    # ── Check 3: console.log in production code ───────────────────────────────
    if _CONSOLE_LOG_RE.search(code_only):
        errors.append("console.log found in production code — remove all console.log statements.")

    # ── Check 4: Raw HTML interactive elements ────────────────────────────────
    if file_type in ("page", "form", "component"):
        if _RAW_BUTTON_RE.search(code_only):
            errors.append(
                "Raw <button> element found — use Button from @msbc/react-toolkit instead."
            )
        if _RAW_ANCHOR_RE.search(code_only):
            errors.append(
                "Raw <a href> element used as interactive element — use Button variant='ghost' instead."
            )
        if _DIV_ONCLICK_RE.search(code_only):
            errors.append(
                "Interactive <div onClick> found — use Button from @msbc/react-toolkit instead."
            )
        if _INLINE_STYLE_RE.search(code_only):
            errors.append(
                "Inline style={{ }} found — use Button variant prop instead of custom styles."
            )

    # ── Check 5: Forbidden field type aliases ─────────────────────────────────
    for pattern, message in _FORBIDDEN_FIELD_TYPES:
        if re.search(pattern, code_only):
            errors.append(message)

    # ── Check 6: Uppercase API method strings ─────────────────────────────────
    match = _UPPERCASE_METHOD_RE.search(code_only)
    if match:
        errors.append(
            f"Uppercase API method found: '{match.group()}' — method must be lowercase "
            "('get' | 'post' | 'patch' | 'delete')."
        )

    # ── Check 7: Forbidden column keys (config files, columnDefs block only) ───
    if file_type == "config" and "columnDefs" in content:
        # Extract the columnDefs array block to scope the regex — avoids
        # false positives from TypeScript interface definitions, options
        # arrays, and other object literals that use the same key names.
        col_block_start = content.find("columnDefs")
        col_block = ""
        if col_block_start != -1:
            bracket_start = content.find("[", col_block_start)
            if bracket_start != -1:
                depth = 0
                buf: list[str] = []
                for ch in content[bracket_start:]:
                    buf.append(ch)
                    if ch == "[":
                        depth += 1
                    elif ch == "]":
                        depth -= 1
                        if depth == 0:
                            break
                col_block = "".join(buf)
        if col_block:
            for pattern, message in _FORBIDDEN_COL_KEYS:
                if re.search(pattern, col_block, re.MULTILINE):
                    errors.append(message)

    # ── Check 8: Action using 'name' or 'label' instead of 'text' ─────────────
    if file_type in ("config", "page") and "actions" in content:
        # Look for { name: 'Xxx' } or { label: 'Xxx' } in an actions context.
        # We use a simple heuristic: these keys appear after 'actions' in the file.
        actions_start = content.find("actions")
        if actions_start != -1:
            actions_block = content[actions_start:]
            if re.search(r"(?<![\w])name\s*:\s*(?:\'|\")[^\'\"]+(?:\'|\")", actions_block):
                errors.append(
                    "Action entry uses 'name' key — use 'text' key instead "
                    "(DashboardConfig actions[].text)."
                )
            if re.search(r"(?<![\w])label\s*:\s*(?:\'|\")[^\'\"]+(?:\'|\")", actions_block):
                errors.append(
                    "Action entry uses 'label' key — use 'text' key instead "
                    "(DashboardConfig actions[].text)."
                )

    # ── Check 9: api inside tableProps (config files) ─────────────────────────
    if file_type == "config" and "tableProps" in content:
        # Check if 'api' key appears inside a tableProps block.
        tp_start = content.find("tableProps")
        if tp_start != -1:
            # Find the matching closing brace of tableProps.
            brace_depth = 0
            tp_block_start = content.find("{", tp_start)
            if tp_block_start != -1:
                tp_block = ""
                for ch in content[tp_block_start:]:
                    tp_block += ch
                    if ch == "{":
                        brace_depth += 1
                    elif ch == "}":
                        brace_depth -= 1
                        if brace_depth == 0:
                            break
                if re.search(r"(?<![\w])api\s*:", tp_block):
                    errors.append(
                        "'api' key found inside 'tableProps' — api must be at the TOP LEVEL "
                        "of DashboardConfig, not nested inside tableProps."
                    )

    # ── Check 10: Field coverage for config/form files ────────────────────────
    if file_type in ("config", "form"):
        for comp in screen_plan.get("components", []):
            for field in comp.get("fields", []):
                field_name = field.get("name", "")
                if field_name and field_name not in content:
                    errors.append(f"Missing field: {field_name}")

    # ── Check 11: Column coverage for config files ────────────────────────────
    if file_type == "config":
        for comp in screen_plan.get("components", []):
            for col in comp.get("columns", []):
                # After spec normalisation the key should be 'field'; fall back to 'name'
                col_name = col.get("field") or col.get("name", "")
                if col_name and col_name not in content:
                    errors.append(f"Missing column: {col_name}")

    # ── Check 12: Data hook usage for service/page files ─────────────────────
    if file_type in ("service", "page"):
        for comp in screen_plan.get("components", []):
            hook = comp.get("data_hook", "")
            if hook and hook not in content:
                errors.append(f"Missing data hook: {hook}")

    # ── Check 13: Toolkit component usage for page/component files ───────────
    if file_type in ("page", "component"):
        for comp in screen_plan.get("components", []):
            mapping = comp.get("toolkit_mapping", "")
            if mapping and mapping not in content:
                errors.append(f"Missing toolkit component: {mapping}")

    # ── Check 14: Forbidden ConfigurableForm props ────────────────────────────
    if file_type in ("form", "page", "component") and "ConfigurableForm" in content:
        for pattern, message in _FORBIDDEN_FORM_PROPS:
            if re.search(pattern, code_only):
                errors.append(message)

    # ── Check 15: Forbidden ConfigurableDashboardHandle methods ──────────────
    if file_type in ("page", "component") and "dashboardRef" in content or "Ref" in content:
        for pattern, message in _FORBIDDEN_HANDLE_METHODS:
            if re.search(pattern, code_only):
                errors.append(message)

    # ── Check 16: Forbidden useApiRequest destructure names ──────────────────
    if file_type in ("service", "page", "form", "hook", "component"):
        match = _FORBIDDEN_APIREQUEST_KEYS_RE.search(code_only)
        if match:
            errors.append(
                "useApiRequest destructures a forbidden key (error/reset/isLoading/mutateAsync). "
                "Only valid keys are: data, loading, apiError, execute."
            )

    # ── Check 17: Default import used for a relative named export ─────────────
    if file_type in ("page", "form", "component", "hook"):
        for m in _DEFAULT_IMPORT_RE.finditer(content):
            line = m.group()
            # Skip 'import React from ...' which is valid
            if "React" not in line:
                errors.append(
                    f"Default import detected for a relative file: '{line.strip()}'. "
                    "Use named import (import {{ Xxx }}) — config/types files use named exports."
                )

    # ── Check 18: Inline interface/type redefinition in non-types files ────────
    if file_type in ("config", "page", "form", "component", "hook", "service"):
        inline_matches = _INLINE_INTERFACE_RE.findall(content)
        if inline_matches:
            errors.append(
                f"Inline interface definition found in a {file_type} file: "
                f"{inline_matches[0].strip()}. "
                "All interfaces must be defined in the module's .types.ts file and imported."
            )

    # ── Check 19: useRef<ConfigurableFormHandle> — type doesn't exist ─────────
    if _FORM_HANDLE_REF_RE.search(content):
        errors.append(
            "useRef<ConfigurableFormHandle> is invalid — ConfigurableFormHandle is not "
            "exported by the toolkit. Remove this ref entirely."
        )

    # ── Check 20: Forbidden root-level DashboardConfig properties ─────────────
    if file_type == "config":
        for pattern, message in _FORBIDDEN_DASHBOARD_ROOT_KEYS:
            if re.search(pattern, code_only, re.MULTILINE):
                errors.append(message)

    # ── Check 21: columnDefs at root of DashboardConfig (not under tableProps) ─
    if file_type == "config" and "DashboardConfig" in content and "columnDefs" in content:
        # Check for columnDefs appearing BEFORE tableProps in the file body —
        # a strong signal it's at the root rather than nested under tableProps.
        col_pos = content.find("columnDefs")
        table_pos = content.find("tableProps")
        if col_pos != -1 and (table_pos == -1 or col_pos < table_pos):
            errors.append(
                "columnDefs appears before tableProps — it must be nested under "
                "tableProps.columnDefs, not at the root of DashboardConfig."
            )

    # ── Check 22: Forbidden JSONFormSchema root keys ───────────────────────────
    if file_type == "config" and "JSONFormSchema" in content:
        for pattern, message in _FORBIDDEN_SCHEMA_ROOT_KEYS:
            if re.search(pattern, code_only, re.MULTILINE):
                errors.append(message)

    # ── Check 23: DashboardConfig filters using 'key' instead of 'name' ───────
    if file_type == "config" and "filters" in content:
        if _FILTER_KEY_RE.search(content):
            errors.append(
                "DashboardConfig filter entry uses 'key:' — the correct property name is 'name:' "
                "(matching BaseFilter<TFilter> interface)."
            )

    return errors


# ---------------------------------------------------------------------------
# Helper: find screen plan for a generated file
# ---------------------------------------------------------------------------


def _find_screen_plan(file: dict, plan_modules: list[dict]) -> dict:
    """
    Return the raw screen plan dict matching the generated file's
    (module_name, screen_name).  Returns an empty dict if not found.
    """
    module_name: str = file.get("module_name", "")
    screen_name: str = file.get("screen_name", "")

    for module in plan_modules:
        if module.get("module_name") != module_name:
            continue
        for screen in module.get("screens", []):
            if screen.get("screen_name") == screen_name:
                return screen

    return {}


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------


def _safe_write_path(output_dir: str, relative_file_path: str) -> Path:
    """Resolve and validate that the target path is inside output_dir."""
    root = Path(output_dir).resolve()
    target = (root / relative_file_path).resolve()
    if not str(target).startswith(str(root)):
        raise ValueError(
            f"Unsafe path outside output_dir: {relative_file_path}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------


async def validate_file(state: ValidatorState) -> dict[str, Any]:
    """
    Node 1 — Run deterministic rule checks on the current file.

    Populates ``_check_errors`` with any failures found.
    """
    idx: int = state["current_file_idx"]
    files: list[dict] = state["generated_files"]

    if idx >= len(files):
        return {"_check_errors": []}

    file = files[idx]
    screen_plan = _find_screen_plan(file, state["plan_modules"])
    errors = _run_checks(file, screen_plan)

    logger.info(
        "[validator] file %d/%d — %s — %d error(s).",
        idx + 1,
        len(files),
        file.get("file_path", "?"),
        len(errors),
    )

    return {"_check_errors": errors}


async def regenerate_file(state: ValidatorState) -> dict[str, Any]:
    """
    Node 2 — Ask the LLM to fix the current file's validation errors.

    Increments retry_count and overwrites the file entry in generated_files
    with the corrected code.  Also writes the fixed code to disk.
    """
    idx: int = state["current_file_idx"]
    files: list[dict] = state["generated_files"]
    file = files[idx]
    errors: list[str] = state.get("_check_errors", [])

    prompt = load_prompt("code_generator/validate_file.yaml")
    errors_text = "\n".join(f"- {e}" for e in errors)

    # Resolve per-file-type fix instructions from the prompt YAML.
    file_type: str = file.get("file_type", "component")
    fix_instructions_dict: dict = prompt.get("file_type_fix_instructions") or {}
    file_type_fix_instructions: str = fix_instructions_dict.get(file_type, "")

    # Provide the screen spec so the fixer knows what must be in the file.
    screen_plan = _find_screen_plan(file, state["plan_modules"])
    screen_plan_json = json.dumps(screen_plan, indent=2) if screen_plan else "{}"

    user_text = prompt._fmt(
        prompt.user_template,
        file_type_fix_instructions=file_type_fix_instructions,
        file_path=file.get("file_path", ""),
        file_type=file_type,
        screen_plan_json=screen_plan_json,
        errors_text=errors_text,
        original_code=file.get("content", ""),
    )

    fixed_code: str = file.get("content", "")
    try:
        result, _ = await call_llm_with_schema(
            system_prompt=prompt.system,
            user_prompt=user_text,
            schema=_FIX_SCHEMA,
            schema_name="validate_file",
        )
        fixed_code = result.get("code", fixed_code)
    except Exception as exc:
        logger.warning(
            "[validator] LLM fixer failed for %s (attempt %d): %s",
            file.get("file_path", "?"),
            state.get("retry_count", 0) + 1,
            exc,
        )

    # Write fixed file to disk only if the code actually changed
    if fixed_code and fixed_code != file.get("content", ""):
        try:
            out_path = _safe_write_path(state["output_dir"], file["file_path"])
            out_path.write_text(fixed_code, encoding="utf-8")
            logger.info("[validator] overwrote %s with fixed code.", out_path)
        except Exception as exc:
            logger.warning(
                "[validator] disk write failed for %s: %s",
                file.get("file_path", "?"),
                exc,
            )

    # Replace the file entry at idx with updated content
    updated_files = list(files)
    updated_files[idx] = {**file, "content": fixed_code}

    return {
        "generated_files": updated_files,
        "retry_count": state.get("retry_count", 0) + 1,
    }


async def advance_validator(state: ValidatorState) -> dict[str, Any]:
    """
    Node 3 — Record the validation result for the current file and advance.

    Appends a validated copy of the file (with validation_passed and
    validation_errors populated) to ``validated_files``.  Resets retry_count
    and _check_errors so the next iteration starts clean.
    """
    idx: int = state["current_file_idx"]
    files: list[dict] = state["generated_files"]
    errors: list[str] = state.get("_check_errors", [])

    file = files[idx] if idx < len(files) else {}
    validated_file = {
        **file,
        "validation_passed": len(errors) == 0,
        "validation_errors": errors,
    }

    logger.info(
        "[validator] advance — %s — passed=%s.",
        file.get("file_path", "?"),
        len(errors) == 0,
    )

    return {
        "validated_files": [validated_file],
        "all_validation_errors": errors,
        "current_file_idx": idx + 1,
        "retry_count": 0,
        "_check_errors": [],
    }


# ---------------------------------------------------------------------------
# Routing functions (used with add_conditional_edges — NOT nodes)
# ---------------------------------------------------------------------------


def decide_retry(state: ValidatorState) -> str:
    """
    Route after validate_file:
    - No errors → advance directly.
    - Errors + retries remain → regenerate.
    - Errors + retries exhausted → advance (record as failed).
    """
    errors: list[str] = state.get("_check_errors", [])
    if not errors:
        return "advance_validator"
    if state.get("retry_count", 0) < MAX_RETRIES:
        return "regenerate_file"
    logger.warning(
        "[validator] max retries (%d) exhausted for %s — recording as failed.",
        MAX_RETRIES,
        state["generated_files"][state["current_file_idx"]].get("file_path", "?"),
    )
    return "advance_validator"


def route_after_advance(state: ValidatorState) -> str:
    """
    Route after advance_validator:
    - More files remain → loop back to validate_file.
    - All files processed → end.
    """
    if state["current_file_idx"] < len(state["generated_files"]):
        return "validate_file"
    return "__end__"


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


def _build_validator_graph() -> Any:
    builder = StateGraph(ValidatorState)

    builder.add_node("validate_file", validate_file)
    builder.add_node("regenerate_file", regenerate_file)
    builder.add_node("advance_validator", advance_validator)

    builder.add_edge(START, "validate_file")

    builder.add_conditional_edges(
        "validate_file",
        decide_retry,
        {
            "advance_validator": "advance_validator",
            "regenerate_file": "regenerate_file",
        },
    )

    builder.add_edge("regenerate_file", "validate_file")

    builder.add_conditional_edges(
        "advance_validator",
        route_after_advance,
        {
            "validate_file": "validate_file",
            "__end__": END,
        },
    )

    return builder.compile()


_validator_workflow = _build_validator_graph()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def run_validation(
    generated_files: list[dict],
    plan_modules: list[dict],
    output_dir: str,
) -> list[dict]:
    """
    Run the validator graph over all generated files.

    Parameters
    ----------
    generated_files
        List of ``GeneratedFile.model_dump()`` dicts from
        ``run_code_generation()``.
    plan_modules
        List of raw ModulePlan dicts (for screen plan lookup during checks).
    output_dir
        Root directory where generated files were written.  The fixer node
        overwrites files here when it produces a corrected version.

    Returns
    -------
    List of file dicts, each augmented with ``validation_passed`` (bool) and
    ``validation_errors`` (list[str]).
    """
    if not generated_files:
        logger.info("[validator] no files to validate — skipping.")
        return []

    logger.info(
        "[validator] run_validation start — %d file(s).", len(generated_files)
    )

    initial_state: ValidatorState = {
        "generated_files": list(generated_files),  # work on a copy
        "plan_modules": plan_modules,
        "output_dir": output_dir,
        "current_file_idx": 0,
        "retry_count": 0,
        "_check_errors": [],
        "validated_files": [],
        "all_validation_errors": [],
    }

    final_state: dict = await _validator_workflow.ainvoke(initial_state)

    validated = final_state.get("validated_files", [])
    total_errors = len(final_state.get("all_validation_errors", []))

    logger.info(
        "[validator] run_validation complete — %d validated, %d total error(s).",
        len(validated),
        total_errors,
    )

    return validated
