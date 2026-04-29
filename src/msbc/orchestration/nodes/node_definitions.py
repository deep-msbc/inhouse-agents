"""
Node implementations for the requirement extractor LangGraph workflow.

Phases:
  0   — segmentation_node     : identify modules (1 LLM call)
  0.5 — build_slices_node     : pure-Python fan-out via Send API
  1   — extract_module_node   : extraction + summary per module (parallel)
  2   — finalize_node         : pure-Python collect + graph-builder LLM call
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import yaml

from src.msbc.agents.schemas.requirement_extractor import (
    BACKEND_SCHEMA,
    COMBINED_SCHEMA,
    FRONTEND_SCHEMA,
    GRAPH_OUTPUT_SCHEMA,
    SEGMENTATION_SCHEMA,
    SUMMARY_SCHEMA,
)
from src.msbc.llm.clients.openai_client import call_llm_with_schema, merge_usage
from src.msbc.orchestration.state import ExtractionState, ModuleResult, ModuleSlice

logger = logging.getLogger(__name__)

# ── Prompt loader ─────────────────────────────────────────────────────────────

_PROMPTS_DIR = (
    Path(__file__).parent.parent.parent  # src/msbc/
    / "llm" / "prompts" / "templates" / "requirement_extractor"
)


def _load_prompt(name: str) -> dict[str, str]:
    """Load a YAML prompt file and return {'system': ..., 'user_template': ...}."""
    path = _PROMPTS_DIR / f"{name}.yaml"
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _fmt(template: str, **kwargs: str) -> str:
    """
    Safe prompt template substitution.

    Uses plain str.replace() instead of str.format() so that JSON examples
    inside the YAML prompt (e.g. {"level": 1}) are never mistaken for
    Python format placeholders, avoiding KeyError on those keys.
    """
    result = template
    for key, value in kwargs.items():
        result = result.replace(f"{{{key}}}", value)
    return result


# ── Document slicing (mirrors _slice_module_text from old llm_service.py) ─────

def _slice_module_text(
    document_text: str,
    module_heading: str,
    next_heading: str | None,
) -> str:
    """
    Extract the text slice for a module by locating its heading in the document.
    Returns from module_heading up to (but not including) next_heading, or end of doc.
    Falls back to the full document if the heading is not found.
    """
    start_idx = document_text.find(module_heading)
    if start_idx == -1:
        start_idx = document_text.lower().find(module_heading.lower())
    if start_idx == -1:
        logger.warning(
            "Heading '%s' not found in document; using full text as fallback.",
            module_heading,
        )
        return document_text

    if next_heading:
        end_idx = document_text.find(next_heading, start_idx + len(module_heading))
        if end_idx == -1:
            end_idx = document_text.lower().find(
                next_heading.lower(), start_idx + len(module_heading)
            )
        if end_idx != -1:
            return document_text[start_idx:end_idx]

    return document_text[start_idx:]


# ── Validation: cross-reference opens_screen (mirrors old _validate_opens_screen_refs) ──

def _validate_opens_screen_refs(
    screen: dict[str, Any], known_screens: set[str]
) -> None:
    """Walk a screen's components and warn about unknown opens_screen references."""
    for comp in screen.get("components", []):
        t = comp.get("type", "")
        if t == "toolbar":
            for action in comp.get("actions", []):
                ref = action.get("opens_screen")
                if ref and ref not in known_screens:
                    logger.warning(
                        "opens_screen '%s' in toolbar action '%s' of screen '%s' "
                        "does not match any defined screen.",
                        ref, action.get("label"), screen.get("name"),
                    )
        elif t == "grid":
            for ra in comp.get("row_actions", []):
                ref = ra.get("opens_screen")
                if ref and ref not in known_screens:
                    logger.warning(
                        "opens_screen '%s' in row_action '%s' of screen '%s' "
                        "does not match any defined screen.",
                        ref, ra.get("label"), screen.get("name"),
                    )
        elif t == "tabs":
            for tab in comp.get("children", []):
                _validate_opens_screen_refs(
                    {"name": screen.get("name"), "components": tab.get("components", [])},
                    known_screens,
                )


# ── Frontend component normalizer ─────────────────────────────────────────────

# Maps the UPPERCASE named-key labels the LLM may emit (from the old prompt
# template) to the correct `type` string expected by the schema.
_COMPONENT_KEY_TO_TYPE: dict[str, str] = {
    "TOOLBAR":        "toolbar",
    "FILTER_PANEL":   "filter_panel",
    "GRID":           "grid",
    "KPI":            "kpi",
    "TABS":           "tabs",
    "FORM":           "form",
    "SCAN_PANEL":     "scan_panel",
    "STEPPER":        "stepper",
    "FEEDBACK_AREA":  "feedback_area",
    "BARCODE_PANEL":  "barcode_panel",
    "INFO_PANEL":     "info_panel",
    "UPLOAD_ZONE":    "upload_zone",
    "TIMELINE":       "timeline",
    "SUMMARY_SECTION": "summary_section",
}


def _unwrap_components(components: list[Any]) -> list[dict[str, Any]]:
    """
    Coerce a components list into the flat-object format the schema expects.

    Handles two malformed formats the LLM may return:
      1. Each array element is a wrapper object whose keys are UPPERCASE type
         labels and whose values are the real component dicts, e.g.
           [{"TOOLBAR": {"id": "tb", "type": "toolbar", ...}, "GRID": {...}}]
         → unwrapped to [{"id": "tb", "type": "toolbar", ...}, {"id": "g", ...}]

      2. The component dict is missing the required `type` field but its
         position under a named key makes the type unambiguous — inferred.
    """
    normalized: list[dict[str, Any]] = []
    for comp in components:
        if not isinstance(comp, dict):
            continue
        if "type" in comp:
            # Already correct flat format — keep as-is (recurse into tabs children)
            if comp.get("type") == "tabs":
                for child in comp.get("children", []):
                    child["components"] = _unwrap_components(
                        child.get("components", [])
                    )
            normalized.append(comp)
        else:
            # Wrapped format: each key is an UPPERCASE label, value is the component
            for key, type_value in _COMPONENT_KEY_TO_TYPE.items():
                if key in comp and isinstance(comp[key], dict):
                    inner = dict(comp[key])
                    if "type" not in inner:
                        inner["type"] = type_value
                    # Recurse into tabs children if present
                    if inner.get("type") == "tabs":
                        for child in inner.get("children", []):
                            child["components"] = _unwrap_components(
                                child.get("components", [])
                            )
                    normalized.append(inner)
    return normalized


def _normalize_extraction(data: dict[str, Any]) -> dict[str, Any]:
    """
    Safety-net normalizer: fix component format when the LLM wraps components
    in UPPERCASE named keys instead of emitting flat objects with `type`.
    Handles both frontend mode (module.screens) and both mode (module.frontend.screens).
    Applied after JSON parsing and before schema validation on every attempt.
    """
    try:
        module = data.get("module", {})
        # frontend mode: module.screens
        for screen in module.get("screens", []):
            screen["components"] = _unwrap_components(screen.get("components", []))
        # both mode: module.frontend.screens
        for screen in module.get("frontend", {}).get("screens", []):
            screen["components"] = _unwrap_components(screen.get("components", []))
    except Exception:
        pass  # Return data unchanged if normalization itself fails
    return data


# ── Phase 0: Segmentation ─────────────────────────────────────────────────────

async def segmentation_node(state: ExtractionState) -> dict[str, Any]:
    """
    Identify top-level modules from the heading hierarchy.
    Mirrors Phase 0 of the original llm_service.py.
    """
    logger.info("segmentation_node: identifying modules from heading hierarchy.")
    prompt_data = _load_prompt("segmentation")

    heading_hierarchy_json = json.dumps(state["heading_hierarchy"], indent=2)
    user_prompt = _fmt(
        prompt_data["user_template"],
        heading_hierarchy=heading_hierarchy_json,
    )

    result, usages = await call_llm_with_schema(
        system_prompt=prompt_data["system"],
        user_prompt=user_prompt,
        schema=SEGMENTATION_SCHEMA,
        schema_name="segmentation",
    )

    modules: list[dict[str, Any]] = result.get("modules", [])
    if not modules:
        # Fallback: treat the whole document as one module
        logger.warning("segmentation_node: no modules found; falling back to single module.")
        modules = [{
            "name": "Application",
            "heading": "",
            "level": 1,
            "description": "Full document",
        }]

    logger.info(
        "segmentation_node: %d module(s) identified: %s",
        len(modules), [m["name"] for m in modules],
    )
    return {"modules": modules, "all_usage": usages}


# ── Phase 0.5: Build slices (fan-out prep) ────────────────────────────────────

def build_slices_node(state: ExtractionState) -> list["Send"]:  # type: ignore[name-defined]
    """
    Slice the document text per module and return a list of Send objects
    to fan-out extract_module_node in parallel.

    This function is used as a conditional-edge function (returns Send objects),
    not a regular node — imported by edge_logic.py.
    """
    from langgraph.types import Send  # local import to avoid circular import at module level

    modules: list[dict[str, Any]] = state["modules"]
    document_text: str = state["document_text"]
    mode: str = state["mode"]

    sends: list[Send] = []
    for idx, module_meta in enumerate(modules):
        heading = module_meta.get("heading", "") or module_meta.get("name", "")
        next_heading = (
            (modules[idx + 1].get("heading", "") or modules[idx + 1].get("name", ""))
            if idx + 1 < len(modules)
            else None
        )
        module_text = _slice_module_text(document_text, heading, next_heading)

        slice_input: ModuleSlice = {
            "index":       idx,
            "module_name": module_meta["name"],
            "module_text": module_text,
            "mode":        mode,
        }
        sends.append(Send("extract_module_node", slice_input))

    logger.info("build_slices_node: fanning out %d module slice(s).", len(sends))
    return sends


# ── Phase 1: Per-module extraction + summary (parallel via Send fan-out) ───────

async def extract_module_node(slice_input: ModuleSlice) -> dict[str, Any]:
    """
    Run extraction + summary for ONE module in parallel (asyncio.gather).
    Mirrors Phase 1 of the original llm_service.py.

    Invoked N times in parallel by the Send fan-out from build_slices_node.
    Each call appends one ModuleResult to state["results"] via the reducer.
    """
    module_name = slice_input["module_name"]
    module_text = slice_input["module_text"]
    mode        = slice_input["mode"]

    logger.info("extract_module_node: extracting '%s' (mode=%s).", module_name, mode)

    summary_prompt  = _load_prompt("summary_extraction")
    base_rules_text = _load_prompt("base_rules").get("rules", "")

    summary_user = _fmt(
        summary_prompt["user_template"],
        module_name=module_name,
        module_text=module_text,
    )

    # ── "both" mode: two focused parallel calls (fe + be) instead of one
    #    giant combined prompt that reliably times out.
    if mode == "both":
        fe_prompt = _load_prompt("frontend_extraction")
        be_prompt = _load_prompt("backend_extraction")

        fe_user = _fmt(
            fe_prompt["user_template"],
            module_name=module_name,
            module_text=module_text,
            base_rules=base_rules_text,
        )
        be_user = _fmt(
            be_prompt["user_template"],
            module_name=module_name,
            module_text=module_text,
            base_rules=base_rules_text,
        )

        (fe_result, fe_usages), (be_result, be_usages), (summary_result, summary_usages) = (
            await asyncio.gather(
                call_llm_with_schema(
                    system_prompt=fe_prompt["system"],
                    user_prompt=fe_user,
                    schema=FRONTEND_SCHEMA,
                    schema_name=f"extraction:fe:{module_name}",
                    normalizer=_normalize_extraction,
                ),
                call_llm_with_schema(
                    system_prompt=be_prompt["system"],
                    user_prompt=be_user,
                    schema=BACKEND_SCHEMA,
                    schema_name=f"extraction:be:{module_name}",
                ),
                call_llm_with_schema(
                    system_prompt=summary_prompt["system"],
                    user_prompt=summary_user,
                    schema=SUMMARY_SCHEMA,
                    schema_name=f"summary:{module_name}",
                ),
            )
        )

        fe_module = fe_result.get("module", {})
        be_module = be_result.get("module", {})

        # Merge into combined schema shape: {"module": {"frontend": ..., "backend": ...}}
        extraction_result: dict[str, Any] = {
            "module": {
                "name":        module_name,
                "description": be_module.get("description") or fe_module.get("description"),
                "frontend": {
                    "screens":         fe_module.get("screens", []),
                    "enums":           fe_module.get("enums", []),
                    "business_rules":  fe_module.get("business_rules", []),
                    "workflows":       fe_module.get("workflows", []),
                },
                "backend": {
                    "api_endpoints":   be_module.get("api_endpoints", []),
                    "models":          be_module.get("models", []),
                    "business_logic":  be_module.get("business_logic", []),
                    "workflows":       be_module.get("workflows", []),
                },
            }
        }
        extraction_usages = fe_usages + be_usages

        # Cross-validate frontend screen references
        _cross_validate_module(extraction_result, mode)

    else:
        # ── Single-call path for frontend / backend ───────────────────────
        mode_map = {
            "frontend": ("frontend_extraction", FRONTEND_SCHEMA),
            "backend":  ("backend_extraction",  BACKEND_SCHEMA),
        }
        prompt_name, extraction_schema = mode_map[mode]
        extraction_prompt = _load_prompt(prompt_name)

        extraction_user = _fmt(
            extraction_prompt["user_template"],
            module_name=module_name,
            module_text=module_text,
            base_rules=base_rules_text,
        )

        extraction_normalizer = _normalize_extraction if mode == "frontend" else None

        (extraction_result, extraction_usages), (summary_result, summary_usages) = (
            await asyncio.gather(
                call_llm_with_schema(
                    system_prompt=extraction_prompt["system"],
                    user_prompt=extraction_user,
                    schema=extraction_schema,
                    schema_name=f"extraction:{module_name}",
                    normalizer=extraction_normalizer,
                ),
                call_llm_with_schema(
                    system_prompt=summary_prompt["system"],
                    user_prompt=summary_user,
                    schema=SUMMARY_SCHEMA,
                    schema_name=f"summary:{module_name}",
                ),
            )
        )

        # Ensure module name is set even if LLM left it blank
        if extraction_result.get("module", {}).get("name", "") == "":
            extraction_result.setdefault("module", {})["name"] = module_name

        if mode == "frontend":
            _cross_validate_module(extraction_result, mode)

    all_usages = extraction_usages + summary_usages
    if mode == "backend":
        logger.info(
            "extract_module_node: '%s' done — %d endpoints, %d models.",
            module_name,
            len((extraction_result.get("module") or {}).get("api_endpoints", [])),
            len((extraction_result.get("module") or {}).get("models", [])),
        )
    elif mode == "both":
        fe = (extraction_result.get("module") or {}).get("frontend", {})
        be = (extraction_result.get("module") or {}).get("backend", {})
        logger.info(
            "extract_module_node: '%s' done — %d screens, %d endpoints, %d models.",
            module_name,
            len(fe.get("screens", [])),
            len(be.get("api_endpoints", [])),
            len(be.get("models", [])),
        )
    else:
        logger.info(
            "extract_module_node: '%s' done — %d screens.",
            module_name,
            _screen_count(extraction_result, mode),
        )

    module_result: ModuleResult = {
        "module_name": module_name,
        "extraction":  extraction_result,
        "summary":     summary_result,
        "usage":       all_usages,
    }
    # Append to the state's results list via the Annotated reducer
    return {"results": [module_result]}


def _cross_validate_module(result: dict[str, Any], mode: str) -> None:
    """Warn about opens_screen references that don't match any screen in this module."""
    if mode == "both":
        screens = (result.get("module") or {}).get("frontend", {}).get("screens", [])
    else:
        screens = (result.get("module") or {}).get("screens", [])

    known: set[str] = {s.get("name", "") for s in screens}
    for screen in screens:
        _validate_opens_screen_refs(screen, known)


def _screen_count(result: dict[str, Any], mode: str) -> int:
    """Count extracted screens for frontend-mode modules only."""
    return len((result.get("module") or {}).get("screens", []))


# ── Phase 2: Finalize (pure-Python collect + graph builder LLM) ──────────────

def _python_merge_results(
    results: list[ModuleResult],
    modules: list[dict[str, Any]],
    mode: str,
) -> dict[str, Any]:
    """
    Pure-Python collect: assemble per-module extractions in segmentation order.
    No LLM call — instant. Mirrors Phase 2 of user_story_parser/llm_service.py.
    """
    order_map: dict[str, int] = {m["name"]: idx for idx, m in enumerate(modules)}
    sorted_results = sorted(
        results, key=lambda r: order_map.get(r["module_name"], 999)
    )

    module_list = [
        {
            "name":  res["module_name"],
            "order": idx + 1,
            **res["extraction"].get("module", {}),
        }
        for idx, res in enumerate(sorted_results)
    ]

    return {
        "mode":          mode,
        "total_modules": len(module_list),
        "modules":       module_list,
    }


async def finalize_node(state: ExtractionState) -> dict[str, Any]:
    """
    Phase 2: Assemble all per-module extractions (pure Python, instant) and
    build the dependency graph (one LLM call on summaries only).

    Replaces the old unification_node (LLM on all extraction JSONs → timeout)
    and graph_builder_node (which ran sequentially after that).
    """
    n = len(state["results"])
    logger.info("finalize_node: assembling %d module(s) + building dependency graph.", n)

    # ── Pure-Python merge (instant) ───────────────────────────────────────────
    extraction = _python_merge_results(state["results"], state["modules"], state["mode"])

    # ── Graph builder LLM call (uses summaries only — small context) ──────────
    prompt_data   = _load_prompt("graph_builder")
    all_summaries = [r["summary"] for r in state["results"]]

    # Build the ordered list of valid module IDs (snake_case) from module names.
    # These are passed explicitly to the LLM so it cannot invent phantom nodes.
    def _to_module_id(name: str) -> str:
        return name.lower().replace(" ", "_").replace("-", "_")

    module_names   = [r["module_name"] for r in state["results"]]
    valid_ids      = [_to_module_id(name) for name in module_names]
    module_ids_json = json.dumps(valid_ids, indent=2)

    user_prompt = _fmt(
        prompt_data["user_template"],
        mode=state["mode"],
        module_ids=module_ids_json,
        module_count=str(len(valid_ids)),
        all_summaries=json.dumps(all_summaries, indent=2),
    )

    graph_result, graph_usages = await call_llm_with_schema(
        system_prompt=_fmt(
            prompt_data["system"],
            mode=state["mode"],
            module_ids=module_ids_json,
        ),
        user_prompt=user_prompt,
        schema=GRAPH_OUTPUT_SCHEMA,
        schema_name="graph_builder",
    )

    # ── Post-process: strip any phantom nodes/edges the LLM may have produced ─
    valid_id_set = set(valid_ids)
    graph = graph_result.get("graph", {})

    # Keep only nodes whose IDs are in the extracted set
    filtered_nodes = [n for n in graph.get("nodes", []) if n.get("id") in valid_id_set]

    # Ensure every extracted module has a node (fill gaps if LLM omitted any)
    existing_ids = {n["id"] for n in filtered_nodes}
    for mid, mname in zip(valid_ids, module_names):
        if mid not in existing_ids:
            filtered_nodes.append({"id": mid, "label": mname, "type": "feature", "description": None, "external_dependencies": []})

    # Keep only edges where both endpoints are valid extracted module IDs
    filtered_edges = [
        e for e in graph.get("edges", [])
        if e.get("from") in valid_id_set and e.get("to") in valid_id_set
    ]

    # Recompute entry_points from filtered graph
    inbound_ids = {
        e["to"] for e in filtered_edges
        if e.get("relation") in ("depends_on", "calls")
    }
    entry_points = [n["id"] for n in filtered_nodes if n["id"] not in inbound_ids]

    graph_result["graph"] = {
        "nodes":        filtered_nodes,
        "edges":        filtered_edges,
        "entry_points": entry_points,
        "metadata": {
            "total_modules": len(filtered_nodes),
            "mode":          state["mode"],
            "total_edges":   len(filtered_edges),
        },
    }

    node_count = len(graph_result.get("graph", {}).get("nodes", []))
    edge_count = len(graph_result.get("graph", {}).get("edges", []))
    logger.info(
        "finalize_node: complete — %d module(s), graph: %d nodes, %d edges.",
        n, node_count, edge_count,
    )
    return {"extraction": extraction, "graph": graph_result["graph"], "all_usage": graph_usages}
