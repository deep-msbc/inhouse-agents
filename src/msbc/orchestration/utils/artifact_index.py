"""
Artifact index builder for Phase 2 post-extraction deduplication.

Reads ModuleResult dicts from state["results"] and produces a flat catalog of
ArtifactSignature dicts grouped by artifact type. All normalization for later
comparison is applied here — the deduplication logic only needs to compare
pre-normalized values.

Handles all three extraction modes: frontend, backend, both.

Artifact types indexed:
  api_endpoints   — from backend's api_endpoints
  db_models       — from backend's models
  enums           — from frontend's enums
  business_rules  — from frontend's business_rules + backend's business_logic
  screens         — from frontend's screens
  workflows       — from frontend/backend workflows
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# ── Normalization utilities ────────────────────────────────────────────────────

def normalize_name(name: str) -> str:
    """Normalize any artifact name to lowercase snake_case for comparison."""
    name = (name or "").strip().lower()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    return name.strip("_") or "unnamed"


def normalize_path(path: str) -> str:
    """
    Normalize an API endpoint path for deduplication comparison.

    Examples:
      /batches/{batchNo}      → /batches/{param}
      /batches/:batchNo       → /batches/{param}
      /api/v1/batches//items  → /api/v1/batches/items
      /Batches                → /batches
    """
    path = (path or "").strip().lower()
    # Replace :param-style path parameters
    path = re.sub(r":([a-zA-Z_][a-zA-Z0-9_]*)", r"{param}", path)
    # Collapse any {xxx}-style params (including already-replaced ones)
    path = re.sub(r"\{[^}]+\}", "{param}", path)
    # Collapse duplicate slashes
    path = re.sub(r"/+", "/", path)
    return path.rstrip("/") or "/"


def normalize_rule_text(text: str) -> str:
    """
    Normalize business rule text for semantic comparison.

    Lowercases and collapses whitespace. Keeps the formula structure intact
    so Jaccard similarity can identify semantically equivalent rules that are
    worded differently (e.g. 'Remaining Quantity = ...' vs 'Available = ...').
    """
    text = (text or "").lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _make_artifact_id(artifact_type: str, module_key: str, discriminator: str) -> str:
    """
    Generate a unique artifact_id for one extracted artifact instance.

    Format: {artifact_type}__{module_key}__{discriminator}
    e.g.  : api_endpoint__production_scanning__post_{param}
    """
    disc = re.sub(r"[^a-z0-9]+", "_", discriminator.lower()).strip("_") or "x"
    return f"{artifact_type}__{module_key}__{disc}"


# ── Per-type extraction helpers ───────────────────────────────────────────────

def _extract_api_endpoints(
    module: dict[str, Any],
    module_key: str,
    source_chunk_ids: list[str],
    mode: str,
) -> list[dict[str, Any]]:
    """Extract api_endpoint ArtifactSignature dicts from one module extraction result."""
    if mode == "both":
        endpoints = module.get("backend", {}).get("api_endpoints", [])
    elif mode == "backend":
        endpoints = module.get("api_endpoints", [])
    else:
        return []  # frontend-only: no endpoints

    sigs: list[dict[str, Any]] = []
    for ep in (endpoints or []):
        if not isinstance(ep, dict):
            continue
        method    = (ep.get("method") or "").upper().strip()
        path      = ep.get("path") or ep.get("endpoint") or ep.get("url") or ""
        name      = ep.get("name") or f"{method} {path}"
        norm_path = normalize_path(path)
        discriminator = f"{method}_{norm_path}"
        sigs.append({
            "artifact_id":        _make_artifact_id("api_endpoint", module_key, discriminator),
            "artifact_type":      "api_endpoint",
            "module_key":         module_key,
            "name":               name,
            "normalized_name":    discriminator,
            "method":             method or None,
            "path":               norm_path,
            "table_name":         None,
            "fields":             ep.get("request_body", {}).get("fields", [])
                                  if isinstance(ep.get("request_body"), dict)
                                  else [],
            "values":             [],
            "source_chunk_ids": list(source_chunk_ids),
            "raw":                ep,
        })
    return sigs


def _extract_db_models(
    module: dict[str, Any],
    module_key: str,
    source_chunk_ids: list[str],
    mode: str,
) -> list[dict[str, Any]]:
    """Extract db_model ArtifactSignature dicts from one module extraction result."""
    if mode == "both":
        models = module.get("backend", {}).get("models", [])
    elif mode == "backend":
        models = module.get("models", [])
    else:
        return []

    sigs: list[dict[str, Any]] = []
    for model in (models or []):
        if not isinstance(model, dict):
            continue
        name       = (model.get("name") or model.get("model") or "").strip()
        table      = (model.get("table_name") or model.get("db_table") or name).strip()
        norm_table = normalize_name(table)
        fields     = model.get("fields", []) or []
        sigs.append({
            "artifact_id":        _make_artifact_id("db_model", module_key, norm_table),
            "artifact_type":      "db_model",
            "module_key":         module_key,
            "name":               name,
            "normalized_name":    norm_table,
            "method":             None,
            "path":               None,
            "table_name":         norm_table,
            "fields":             fields,
            "values":             [],
            "source_chunk_ids": list(source_chunk_ids),
            "raw":                model,
        })
    return sigs


def _extract_enums(
    module: dict[str, Any],
    module_key: str,
    source_chunk_ids: list[str],
    mode: str,
) -> list[dict[str, Any]]:
    """Extract enum ArtifactSignature dicts from one module extraction result."""
    if mode == "both":
        enums = module.get("frontend", {}).get("enums", [])
    elif mode == "frontend":
        enums = module.get("enums", [])
    else:
        return []

    sigs: list[dict[str, Any]] = []
    for enum in (enums or []):
        if not isinstance(enum, dict):
            continue
        name   = (enum.get("name") or "").strip()
        values = [str(v) for v in (enum.get("values") or [])]
        norm   = normalize_name(name)
        sigs.append({
            "artifact_id":        _make_artifact_id("enum", module_key, norm),
            "artifact_type":      "enum",
            "module_key":         module_key,
            "name":               name,
            "normalized_name":    norm,
            "method":             None,
            "path":               None,
            "table_name":         None,
            "fields":             [],
            "values":             values,
            "source_chunk_ids": list(source_chunk_ids),
            "raw":                enum,
        })
    return sigs


def _extract_business_rules(
    module: dict[str, Any],
    module_key: str,
    source_chunk_ids: list[str],
    mode: str,
) -> list[dict[str, Any]]:
    """Extract business_rule ArtifactSignature dicts from one module extraction result."""
    if mode == "both":
        fe_rules = module.get("frontend", {}).get("business_rules", [])
        be_rules = module.get("backend", {}).get("business_logic", [])
        rules    = (fe_rules or []) + (be_rules or [])
    elif mode == "frontend":
        rules = module.get("business_rules", []) or []
    else:
        rules = module.get("business_logic", []) or []

    sigs: list[dict[str, Any]] = []
    for i, rule in enumerate(rules):
        if isinstance(rule, str):
            text = rule
            name = rule[:80]
        elif isinstance(rule, dict):
            text = (
                rule.get("rule")
                or rule.get("description")
                or rule.get("text")
                or rule.get("formula")
                or str(rule)
            )
            name = rule.get("name") or rule.get("rule") or text[:80]
        else:
            continue
        norm        = normalize_rule_text(text)
        # Discriminator: index + first 40 chars of normalized text (unique per module)
        discriminator = f"r{i}_{norm[:40]}"
        sigs.append({
            "artifact_id":        _make_artifact_id("business_rule", module_key, discriminator),
            "artifact_type":      "business_rule",
            "module_key":         module_key,
            "name":               str(name)[:120],
            "normalized_name":    norm,
            "method":             None,
            "path":               None,
            "table_name":         None,
            "fields":             [],
            "values":             [],
            "source_chunk_ids": list(source_chunk_ids),
            "raw":                {"text": text} if isinstance(rule, str) else rule,
        })
    return sigs


def _extract_screens(
    module: dict[str, Any],
    module_key: str,
    source_chunk_ids: list[str],
    mode: str,
) -> list[dict[str, Any]]:
    """Extract screen ArtifactSignature dicts from one module extraction result."""
    if mode == "both":
        screens = module.get("frontend", {}).get("screens", [])
    elif mode == "frontend":
        screens = module.get("screens", [])
    else:
        return []

    sigs: list[dict[str, Any]] = []
    for screen in (screens or []):
        if not isinstance(screen, dict):
            continue
        name = (screen.get("name") or "").strip()
        norm = normalize_name(name)
        sigs.append({
            "artifact_id":        _make_artifact_id("screen", module_key, norm),
            "artifact_type":      "screen",
            "module_key":         module_key,
            "name":               name,
            "normalized_name":    norm,
            "method":             None,
            "path":               None,
            "table_name":         None,
            "fields":             [],
            "values":             [],
            "source_chunk_ids": list(source_chunk_ids),
            "raw":                screen,
        })
    return sigs


def _extract_workflows(
    module: dict[str, Any],
    module_key: str,
    source_chunk_ids: list[str],
    mode: str,
) -> list[dict[str, Any]]:
    """Extract workflow ArtifactSignature dicts from one module extraction result."""
    if mode == "both":
        fe_flows = module.get("frontend", {}).get("workflows", [])
        be_flows = module.get("backend", {}).get("workflows", [])
        workflows = (fe_flows or []) + (be_flows or [])
    elif mode == "frontend":
        workflows = module.get("workflows", []) or []
    else:
        workflows = module.get("workflows", []) or []

    sigs: list[dict[str, Any]] = []
    for i, flow in enumerate(workflows):
        if isinstance(flow, str):
            name = flow[:80]
            raw  = {"text": flow}
        elif isinstance(flow, dict):
            name = (
                flow.get("name")
                or flow.get("title")
                or flow.get("step")
                or f"Workflow {i + 1}"
            )
            raw  = flow
        else:
            continue
        norm          = normalize_name(str(name))
        discriminator = f"w{i}_{norm[:40]}"
        sigs.append({
            "artifact_id":        _make_artifact_id("workflow", module_key, discriminator),
            "artifact_type":      "workflow",
            "module_key":         module_key,
            "name":               str(name)[:120],
            "normalized_name":    norm,
            "method":             None,
            "path":               None,
            "table_name":         None,
            "fields":             [],
            "values":             [],
            "source_chunk_ids": list(source_chunk_ids),
            "raw":                raw,
        })
    return sigs


# ── Public entry point ─────────────────────────────────────────────────────────

def build_artifact_index(
    results: list[dict[str, Any]],
    mode: str,
) -> dict[str, list[dict[str, Any]]]:
    """
    Build a catalog of ArtifactSignature dicts grouped by artifact type.

    Args:
        results: state["results"] — list of ModuleResult dicts from extract_module_node.
        mode:    extraction mode passed to the pipeline ("frontend" | "backend" | "both").

    Returns:
        {
            "api_endpoints":  [ArtifactSignature dicts …],
            "db_models":      [ArtifactSignature dicts …],
            "enums":          [ArtifactSignature dicts …],
            "business_rules": [ArtifactSignature dicts …],
            "screens":        [ArtifactSignature dicts …],
            "workflows":      [ArtifactSignature dicts …],
        }

    Each artifact instance retains its originating module_key so that the
    deduplication layer can attribute canonical choices and log which modules
    contributed to a merged or conflicting artifact.
    """
    index: dict[str, list[dict[str, Any]]] = {
        "api_endpoints":  [],
        "db_models":      [],
        "enums":          [],
        "business_rules": [],
        "screens":        [],
        "workflows":      [],
    }

    for result in results:
        module_key        = (result.get("module_key") or "").strip()
        source_chunk_ids  = result.get("source_chunk_ids") or []
        extraction        = result.get("extraction") or {}
        module            = extraction.get("module") or {}

        if not module_key:
            # Derive from module_name if module_key was not set (legacy path)
            module_key = normalize_name(result.get("module_name") or "unknown")

        try:
            index["api_endpoints"].extend(
                _extract_api_endpoints(module, module_key, source_chunk_ids, mode)
            )
        except Exception as exc:
            logger.debug(
                "build_artifact_index: api_endpoints error for %r: %s", module_key, exc
            )

        try:
            index["db_models"].extend(
                _extract_db_models(module, module_key, source_chunk_ids, mode)
            )
        except Exception as exc:
            logger.debug(
                "build_artifact_index: db_models error for %r: %s", module_key, exc
            )

        try:
            index["enums"].extend(
                _extract_enums(module, module_key, source_chunk_ids, mode)
            )
        except Exception as exc:
            logger.debug(
                "build_artifact_index: enums error for %r: %s", module_key, exc
            )

        try:
            index["business_rules"].extend(
                _extract_business_rules(module, module_key, source_chunk_ids, mode)
            )
        except Exception as exc:
            logger.debug(
                "build_artifact_index: business_rules error for %r: %s", module_key, exc
            )

        try:
            index["screens"].extend(
                _extract_screens(module, module_key, source_chunk_ids, mode)
            )
        except Exception as exc:
            logger.debug(
                "build_artifact_index: screens error for %r: %s", module_key, exc
            )

        try:
            index["workflows"].extend(
                _extract_workflows(module, module_key, source_chunk_ids, mode)
            )
        except Exception as exc:
            logger.debug(
                "build_artifact_index: workflows error for %r: %s", module_key, exc
            )

    logger.info(
        "build_artifact_index: indexed %d endpoints, %d models, %d enums, "
        "%d rules, %d screens, %d workflows from %d module(s).",
        len(index["api_endpoints"]),
        len(index["db_models"]),
        len(index["enums"]),
        len(index["business_rules"]),
        len(index["screens"]),
        len(index["workflows"]),
        len(results),
    )
    return index
