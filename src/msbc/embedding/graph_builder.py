"""
KUZU graph builder — creates and populates the toolkit knowledge graph.

Two public entry points
-----------------------
build_graph(db_path)
    Opens (or creates) the on-disk KUZU database at *db_path*, runs schema
    DDL (idempotent ``IF NOT EXISTS``), then populates all nodes and edges
    from two sources:

    1. ``toolkit_knowledge.PACKAGES`` dict — Package, Component, TypeDef,
       Feature, FieldType nodes + all relationships between them.
    2. ``correct_code_examples/`` folder on disk — Example, ExampleFile nodes
       + HasFile, DemonstratesComponent, ExhibitsFeature, ExhibitsFieldType edges.

rebuild_graph(db_path)
    Drops every table in reverse-dependency order, then calls build_graph.
    Use with the ``--rebuild`` CLI flag to start from a clean slate.

KUZU insert strategy
--------------------
We use ``MERGE`` for all node inserts so duplicate runs are safe.
Relationships are inserted with ``MATCH … CREATE (a)-[:R]->(b)`` wrapped
in try/except so a duplicate edge just logs a debug message and does not
abort the build.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import kuzu

from src.msbc.agents.frontend_planner.toolkit_knowledge import PACKAGES
from src.msbc.embedding.chunker import (
    _detect_complexity,
    _detect_dashboard_features,
    _detect_example_pattern,
    _detect_file_role,
    _detect_form_features,
    _generate_use_case,
)
from src.msbc.embedding.graph_schema import (
    ALL_DDL,
    ALL_FEATURES,
    ALL_FIELD_TYPES,
    DROP_ORDER,
)
from src.msbc.embedding.ingestors.examples_ingestor import (
    _EXAMPLE_EXTS,
    _content_hash,
    _dominant_pattern,
    _max_complexity,
    _union_features,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _esc(s: str) -> str:
    """Escape single quotes in a string for inline Cypher literals."""
    return s.replace("'", "\\'")


def _cypher_str_list(items: list[str]) -> str:
    """Render a Python list of strings as a Kuzu STRING[] literal, e.g. ['a', 'b']."""
    inner = ", ".join(f"'{_esc(i)}'" for i in items)
    return f"[{inner}]"


def _exec(conn: kuzu.Connection, cypher: str) -> None:
    """Execute a Cypher statement, logging it at DEBUG level."""
    logger.debug("KUZU: %s", cypher.strip()[:120])
    conn.execute(cypher)


def _exec_safe(conn: kuzu.Connection, cypher: str, label: str = "") -> None:
    """
    Execute a Cypher statement; swallow errors (log at DEBUG).

    Used for duplicate-edge inserts where KUZU raises a runtime error when
    the same relationship already exists rather than silently ignoring it.
    """
    try:
        conn.execute(cypher)
    except Exception as exc:  # noqa: BLE001
        logger.debug("KUZU [%s] non-fatal: %s | cypher: %s", label, exc, cypher.strip()[:80])


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def _create_schema(conn: kuzu.Connection) -> None:
    """Execute all ``CREATE … IF NOT EXISTS`` DDL statements from graph_schema.py."""
    for stmt in ALL_DDL:
        stmt = stmt.strip()
        if stmt:
            _exec(conn, stmt)
    logger.info("KUZU schema applied (%d statements).", len(ALL_DDL))


# ---------------------------------------------------------------------------
# Package + Component population
# ---------------------------------------------------------------------------

def _populate_packages_and_components(conn: kuzu.Connection) -> None:
    """
    Walk ``toolkit_knowledge.PACKAGES`` and insert:
    - Package nodes
    - Component nodes (with when_to_use / do_not_use_when lists)
    - TypeDef nodes (inferred from field_types / key_config_rules)
    - Feature nodes (pre-seeded from graph_schema.ALL_FEATURES)
    - FieldType nodes (pre-seeded from graph_schema.ALL_FIELD_TYPES)
    - BelongsTo edges   (Component → Package)
    - InternallyUses edges (Component → Component)
    - UsesType edges   (Component → TypeDef, where config type is known)
    - ExhibitsFeature edges (Component → Feature)
    - SupportsFieldType edges (Component → FieldType)
    """

    # ── Pre-seed Feature + FieldType lookup nodes ─────────────────────────────
    for feat_name, feat_label in ALL_FEATURES:
        _exec(conn, (
            f"MERGE (:Feature {{name: '{_esc(feat_name)}', "
            f"label: '{_esc(feat_label)}'}})"
        ))

    for ft in ALL_FIELD_TYPES:
        _exec(conn, f"MERGE (:FieldType {{name: '{_esc(ft)}'}})")

    logger.info(
        "Seeded %d Feature nodes and %d FieldType nodes.",
        len(ALL_FEATURES), len(ALL_FIELD_TYPES),
    )

    # ── Build a flat component registry for later cross-package edge lookups ──
    # Maps component_name → component_node_id (used when creating InternallyUses)
    comp_id_map: dict[str, str] = {}

    # ── Packages + Component nodes ────────────────────────────────────────────
    for pkg_key, pkg in PACKAGES.items():
        import_path = pkg["import_path"]
        description = pkg.get("description", "")

        # Package node — PK = import_path (same as name field)
        _exec(conn, (
            f"MERGE (:Package {{"
            f"name: '{_esc(import_path)}', "
            f"import_path: '{_esc(import_path)}', "
            f"description: '{_esc(description)}'"
            f"}})"
        ))

        # Support both "components" (config-ui, react-toolkit, …) and
        # "exports" (data-layer, utils) which use the same string/dict value format.
        components_and_exports = {
            **pkg.get("components", {}),
            **pkg.get("exports", {}),
        }
        if not components_and_exports:
            continue

        for comp_name, comp_meta in components_and_exports.items():
            comp_id = f"{import_path}::{comp_name}"

            if isinstance(comp_meta, str):
                # Simple string description (react-toolkit primitives)
                comp_desc = comp_meta
                when_to_use: list[str] = []
                do_not_use_when: list[str] = []
            else:
                comp_desc = comp_meta.get("description", "")
                when_to_use = comp_meta.get("when_to_use", [])
                do_not_use_when = comp_meta.get("do_not_use_when", [])

            # Determine component_type from the key name
            comp_type = _infer_component_type(comp_name, import_path)

            _exec(conn, (
                f"MERGE (:Component {{"
                f"id: '{_esc(comp_id)}', "
                f"name: '{_esc(comp_name)}', "
                f"component_type: '{_esc(comp_type)}', "
                f"description: '{_esc(comp_desc)}', "
                f"when_to_use: {_cypher_str_list(when_to_use)}, "
                f"do_not_use_when: {_cypher_str_list(do_not_use_when)}"
                f"}})"
            ))

            comp_id_map[comp_name] = comp_id

            # BelongsTo edge
            _exec_safe(conn, (
                f"MATCH (c:Component {{id: '{_esc(comp_id)}'}}), "
                f"(p:Package {{name: '{_esc(import_path)}'}}) "
                f"CREATE (c)-[:BelongsTo]->(p)"
            ), label="BelongsTo")

    logger.info("Inserted %d Component nodes.", len(comp_id_map))

    # ── TypeDef nodes (config-ui only — known named types) ───────────────────
    _insert_typedefs(conn, import_path_filter="@msbc/config-ui")

    # ── InternallyUses edges ──────────────────────────────────────────────────
    for pkg_key, pkg in PACKAGES.items():
        import_path = pkg["import_path"]
        components_and_exports = {
            **pkg.get("components", {}),
            **pkg.get("exports", {}),
        }
        for comp_name, comp_meta in components_and_exports.items():
            if not isinstance(comp_meta, dict):
                continue

            comp_id = f"{import_path}::{comp_name}"
            for used_name in comp_meta.get("internally_uses", []):
                used_id = comp_id_map.get(used_name)
                if not used_id:
                    # Component from another package — try to find it
                    used_id = _find_comp_id(used_name, comp_id_map)
                if used_id:
                    _exec_safe(conn, (
                        f"MATCH (a:Component {{id: '{_esc(comp_id)}'}}), "
                        f"(b:Component {{id: '{_esc(used_id)}'}}) "
                        f"CREATE (a)-[:InternallyUses {{note: ''}}]->(b)"
                    ), label="InternallyUses")

    # ── UsesHook edges (data_layer_hooks) ─────────────────────────────────────
    _hook_ids = {name: cid for name, cid in comp_id_map.items()}

    for pkg_key, pkg in PACKAGES.items():
        import_path = pkg["import_path"]
        components_and_exports = {
            **pkg.get("components", {}),
            **pkg.get("exports", {}),
        }
        for comp_name, comp_meta in components_and_exports.items():
            if not isinstance(comp_meta, dict):
                continue
            comp_id = f"{import_path}::{comp_name}"
            for hook_raw in comp_meta.get("data_layer_hooks", []):
                # hook_raw might be "useApiRequest (for ...)" — extract first word
                hook_name = hook_raw.split()[0].rstrip("(")
                hook_id = _hook_ids.get(hook_name)
                if hook_id:
                    _exec_safe(conn, (
                        f"MATCH (c:Component {{id: '{_esc(comp_id)}'}}), "
                        f"(h:Component {{id: '{_esc(hook_id)}'}}) "
                        f"CREATE (c)-[:UsesHook]->(h)"
                    ), label="UsesHook")

    # ── UsesType edges (ConfigurableDashboard / ConfigurableForm → TypeDef) ───
    _insert_usestype_edges(conn)

    # ── ExhibitsFeature edges — feature capability mapping ────────────────────
    _insert_component_feature_edges(conn, comp_id_map)

    # ── SupportsFieldType edges ───────────────────────────────────────────────
    _insert_supports_fieldtype_edges(conn, comp_id_map)

    logger.info("Package + component graph population complete.")


def _infer_component_type(name: str, import_path: str) -> str:
    """Coarsely classify a component/export name into a component_type string."""
    if name.startswith("use") and len(name) > 3 and name[3].isupper():
        return "hook"
    if "Dashboard" in name or "UserList" in name:
        return "dashboard"
    if "Form" in name:
        return "form"
    if "Shell" in name or "Route" in name or "App" in name:
        return "shell"
    if "Wizard" in name:
        return "wizard"
    return "component"


def _find_comp_id(comp_name: str, comp_id_map: dict[str, str]) -> str | None:
    """Return the first comp_id whose key ends with the given component name."""
    return comp_id_map.get(comp_name)


def _insert_typedefs(conn: kuzu.Connection, import_path_filter: str) -> None:
    """Insert known TypeDef nodes for the config-ui package."""
    typedefs = [
        {
            "id": f"{import_path_filter}::DashboardConfig",
            "name": "DashboardConfig",
            "description": (
                "Top-level config object accepted by ConfigurableDashboard. "
                "Controls columns, filters, actions, pagination and API."
            ),
            "required_fields": ["api", "columns"],
        },
        {
            "id": f"{import_path_filter}::JSONFormSchema",
            "name": "JSONFormSchema",
            "description": (
                "Generic form schema type accepted by ConfigurableForm. "
                "Contains sections[] with fields[] per section."
            ),
            "required_fields": ["sections"],
        },
        {
            "id": f"{import_path_filter}::FilterConfig",
            "name": "FilterConfig",
            "description": "Individual filter definition within DashboardConfig.filters[].",
            "required_fields": ["key", "label", "type"],
        },
        {
            "id": f"{import_path_filter}::ColumnDef",
            "name": "ColumnDef",
            "description": "Column definition within DashboardConfig.columns[].",
            "required_fields": ["field", "headerName"],
        },
        {
            "id": f"{import_path_filter}::FormFieldConfig",
            "name": "FormFieldConfig",
            "description": "Individual field definition within a form section.",
            "required_fields": ["name", "label", "type"],
        },
    ]

    for td in typedefs:
        _exec(conn, (
            f"MERGE (:TypeDef {{"
            f"id: '{_esc(td['id'])}', "
            f"name: '{_esc(td['name'])}', "
            f"description: '{_esc(td['description'])}', "
            f"required_fields: {_cypher_str_list(td['required_fields'])}"
            f"}})"
        ))

    # UsesType edges for ConfigurableDashboard
    dashboard_id = f"{import_path_filter}::ConfigurableDashboard"
    for td_name, role in [
        ("DashboardConfig", "config_prop"),
        ("FilterConfig",    "filter_element"),
        ("ColumnDef",       "column_element"),
    ]:
        td_id = f"{import_path_filter}::{td_name}"
        _exec_safe(conn, (
            f"MATCH (c:Component {{id: '{_esc(dashboard_id)}'}}), "
            f"(t:TypeDef {{id: '{_esc(td_id)}'}}) "
            f"CREATE (c)-[:UsesType {{role: '{_esc(role)}'}}]->(t)"
        ), label="UsesType")

    # UsesType edges for ConfigurableForm
    form_id = f"{import_path_filter}::ConfigurableForm"
    for td_name, role in [
        ("JSONFormSchema",  "config_prop"),
        ("FormFieldConfig", "field_element"),
    ]:
        td_id = f"{import_path_filter}::{td_name}"
        _exec_safe(conn, (
            f"MATCH (c:Component {{id: '{_esc(form_id)}'}}), "
            f"(t:TypeDef {{id: '{_esc(td_id)}'}}) "
            f"CREATE (c)-[:UsesType {{role: '{_esc(role)}'}}]->(t)"
        ), label="UsesType")

    logger.info("Inserted %d TypeDef nodes.", len(typedefs))


def _insert_usestype_edges(conn: kuzu.Connection) -> None:
    """Placeholder — TypeDef edges are already inserted in _insert_typedefs."""
    pass


def _insert_component_feature_edges(
    conn: kuzu.Connection, comp_id_map: dict[str, str]
) -> None:
    """
    Create ExhibitsFeature edges for components whose descriptions or
    key_config_rules signal specific capabilities.
    """
    # ConfigurableDashboard exhibits all dashboard features
    dashboard_features = [
        "has_search", "has_filters", "has_actions", "has_list_view",
        "has_mode_switch", "has_pagination", "has_advance_filters",
        "has_api_integration", "has_row_selection",
    ]
    cd_id = "@msbc/config-ui::ConfigurableDashboard"
    for feat in dashboard_features:
        _exec_safe(conn, (
            f"MATCH (c:Component {{id: '{_esc(cd_id)}'}}), "
            f"(f:Feature {{name: '{_esc(feat)}'}}) "
            f"CREATE (c)-[:ExhibitsFeature]->(f)"
        ), label="ExhibitsFeature")

    # ConfigurableForm exhibits all form features
    form_features = [
        "has_sections", "has_nested_groups", "has_custom_validators",
        "has_custom_component", "has_conditional_visibility",
        "has_conditional_validation", "has_dependent_fields", "has_file_upload",
    ]
    cf_id = "@msbc/config-ui::ConfigurableForm"
    for feat in form_features:
        _exec_safe(conn, (
            f"MATCH (c:Component {{id: '{_esc(cf_id)}'}}), "
            f"(f:Feature {{name: '{_esc(feat)}'}}) "
            f"CREATE (c)-[:ExhibitsFeature]->(f)"
        ), label="ExhibitsFeature")


def _insert_supports_fieldtype_edges(
    conn: kuzu.Connection, comp_id_map: dict[str, str]
) -> None:
    """Create SupportsFieldType edges for ConfigurableForm."""
    cf_id = "@msbc/config-ui::ConfigurableForm"
    form_field_types = [
        "text", "email", "number", "password", "textarea", "tel",
        "select", "radio", "checkbox", "list",
        "fileUpload", "map", "date", "date-range",
    ]
    for ft in form_field_types:
        _exec_safe(conn, (
            f"MATCH (c:Component {{id: '{_esc(cf_id)}'}}), "
            f"(ft:FieldType {{name: '{_esc(ft)}'}}) "
            f"CREATE (c)-[:SupportsFieldType]->(ft)"
        ), label="SupportsFieldType")


# ---------------------------------------------------------------------------
# Example folder population
# ---------------------------------------------------------------------------

def _populate_examples(conn: kuzu.Connection, examples_dir: Path) -> None:
    """
    Walk *examples_dir* two levels deep (group → example_id) and insert:
    - Example nodes
    - ExampleFile nodes
    - HasFile edges
    - DemonstratesComponent edges
    - ExhibitsFeature edges (Example → Feature)
    - ExhibitsFieldType edges (Example → FieldType)
    """
    if not examples_dir.exists():
        logger.warning("examples_dir not found: %s — skipping example population.", examples_dir)
        return

    example_count = 0
    file_count = 0

    for group_dir in sorted(examples_dir.iterdir()):
        if not group_dir.is_dir():
            continue
        example_group = group_dir.name

        for example_dir in sorted(group_dir.iterdir()):
            if not example_dir.is_dir():
                continue
            example_id = example_dir.name

            source_files = sorted(
                f for f in example_dir.iterdir()
                if f.is_file() and f.suffix.lower() in _EXAMPLE_EXTS
            )
            if not source_files:
                continue

            # ── Per-file analysis ────────────────────────────────────────────
            file_analyses: list[dict[str, Any]] = []

            for fp in source_files:
                try:
                    content = fp.read_text(encoding="utf-8", errors="replace")
                except OSError as exc:
                    logger.warning("Cannot read '%s': %s", fp, exc)
                    continue

                rel_fp = str(fp.relative_to(examples_dir.parent)).replace("\\", "/")
                pattern = _detect_example_pattern(content, rel_fp)
                file_role = _detect_file_role(fp.name, content)
                features: dict[str, Any] = {}
                if pattern == "ConfigurableDashboard":
                    features = _detect_dashboard_features(content)
                elif pattern == "ConfigurableForm":
                    features = _detect_form_features(content)

                complexity = _detect_complexity(content, file_role, features)
                file_analyses.append({
                    "fp":         fp,
                    "rel_fp":     rel_fp,
                    "file_name":  fp.name,
                    "file_role":  file_role,
                    "pattern":    pattern,
                    "features":   features,
                    "complexity": complexity,
                })

            if not file_analyses:
                continue

            # ── Aggregate ────────────────────────────────────────────────────
            aggregate_pattern = _dominant_pattern([a["pattern"] for a in file_analyses])
            agg_features      = _union_features([a["features"] for a in file_analyses])
            max_complexity    = _max_complexity([a["complexity"] for a in file_analyses])
            use_case = _generate_use_case(example_id, aggregate_pattern, "summary", agg_features)

            # ── Example node ─────────────────────────────────────────────────
            _exec(conn, (
                f"MERGE (:Example {{"
                f"example_id: '{_esc(example_id)}', "
                f"example_group: '{_esc(example_group)}', "
                f"pattern: '{_esc(aggregate_pattern)}', "
                f"complexity: '{_esc(max_complexity)}', "
                f"use_case: '{_esc(use_case)}', "
                f"qdrant_chunk_ids: []"
                f"}})"
            ))
            example_count += 1

            # ── ExampleFile nodes + HasFile edges ────────────────────────────
            for analysis in file_analyses:
                ef_id = f"{example_id}::{analysis['file_name']}"
                _exec(conn, (
                    f"MERGE (:ExampleFile {{"
                    f"id: '{_esc(ef_id)}', "
                    f"file_name: '{_esc(analysis['file_name'])}', "
                    f"file_role: '{_esc(analysis['file_role'])}', "
                    f"file_path: '{_esc(analysis['rel_fp'])}', "
                    f"qdrant_chunk_id: ''"
                    f"}})"
                ))
                file_count += 1

                _exec_safe(conn, (
                    f"MATCH (e:Example {{example_id: '{_esc(example_id)}'}}), "
                    f"(ef:ExampleFile {{id: '{_esc(ef_id)}'}}) "
                    f"CREATE (e)-[:HasFile]->(ef)"
                ), label="HasFile")

            # ── DemonstratesComponent edges ───────────────────────────────────
            if aggregate_pattern in ("ConfigurableDashboard", "ConfigurableForm"):
                comp_id = f"@msbc/config-ui::{aggregate_pattern}"
                _exec_safe(conn, (
                    f"MATCH (e:Example {{example_id: '{_esc(example_id)}'}}), "
                    f"(c:Component {{id: '{_esc(comp_id)}'}}) "
                    f"CREATE (e)-[:DemonstratesComponent]->(c)"
                ), label="DemonstratesComponent")

            # ── ExhibitsFeature edges ────────────────────────────────────────
            for feat_name, _ in ALL_FEATURES:
                if agg_features.get(feat_name, False):
                    _exec_safe(conn, (
                        f"MATCH (e:Example {{example_id: '{_esc(example_id)}'}}), "
                        f"(f:Feature {{name: '{_esc(feat_name)}'}}) "
                        f"CREATE (e)-[:ExhibitsFeature]->(f)"
                    ), label="ExhibitsFeature")

            # ── ExhibitsFieldType edges ──────────────────────────────────────
            for ft in agg_features.get("field_types_used", []):
                if ft in ALL_FIELD_TYPES:
                    _exec_safe(conn, (
                        f"MATCH (e:Example {{example_id: '{_esc(example_id)}'}}), "
                        f"(ft:FieldType {{name: '{_esc(ft)}'}}) "
                        f"CREATE (e)-[:ExhibitsFieldType]->(ft)"
                    ), label="ExhibitsFieldType")

    logger.info(
        "Example graph population complete — %d examples, %d files.",
        example_count, file_count,
    )


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def build_graph(db_path: str, examples_dir: Path | None = None) -> None:
    """
    Create/open the KUZU on-disk database at *db_path*, apply schema DDL, and
    populate nodes + edges from ``toolkit_knowledge.PACKAGES`` and
    ``correct_code_examples/``.

    Safe to call multiple times — ``IF NOT EXISTS`` and ``MERGE`` make all
    operations idempotent.

    Parameters
    ----------
    db_path :
        Path to the on-disk ``.kuzu`` directory (created automatically).
    examples_dir :
        Root of the ``correct_code_examples/`` directory.  Defaults to
        ``Path("correct_code_examples")`` relative to the current working
        directory.
    """
    import os
    # Only ensure the *parent* directory exists.  KUZU creates the db_path
    # directory itself; pre-creating it causes a RuntimeError.
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    db = kuzu.Database(db_path)
    conn = kuzu.Connection(db)

    logger.info("Building KUZU graph at '%s' …", db_path)

    _create_schema(conn)
    _populate_packages_and_components(conn)

    if examples_dir is None:
        examples_dir = Path("correct_code_examples")
    _populate_examples(conn, examples_dir.resolve())

    _log_counts(conn)
    logger.info("KUZU graph build complete.")


def rebuild_graph(db_path: str, examples_dir: Path | None = None) -> None:
    """
    Drop all tables and rebuild the graph from scratch.

    Parameters
    ----------
    db_path :
        Path to the existing (or new) ``.kuzu`` directory.
    examples_dir :
        See :func:`build_graph`.
    """
    # Only ensure the *parent* directory exists.
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    db = kuzu.Database(db_path)
    conn = kuzu.Connection(db)

    logger.info("Rebuilding KUZU graph at '%s' — dropping all tables …", db_path)

    for table_name in DROP_ORDER:
        try:
            conn.execute(f"DROP TABLE {table_name}")
            logger.debug("Dropped table: %s", table_name)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Drop %s (non-fatal): %s", table_name, exc)

    logger.info("All tables dropped. Rebuilding …")

    _create_schema(conn)
    _populate_packages_and_components(conn)

    if examples_dir is None:
        examples_dir = Path("correct_code_examples")
    _populate_examples(conn, examples_dir.resolve())

    _log_counts(conn)
    logger.info("KUZU graph rebuild complete.")


# ---------------------------------------------------------------------------
# Count logger
# ---------------------------------------------------------------------------

def _log_counts(conn: kuzu.Connection) -> None:
    """Log node and edge counts per table after a build."""
    node_tables = [
        "Package", "Component", "TypeDef",
        "Feature", "FieldType", "Example", "ExampleFile",
    ]
    rel_tables = [
        "BelongsTo", "InternallyUses", "UsesType", "UsesHook",
        "ExhibitsFeature", "SupportsFieldType",
        "DemonstratesComponent", "ExhibitsFieldType", "HasFile",
    ]

    lines: list[str] = ["\nKUZU graph node counts:"]
    for table in node_tables:
        try:
            res = conn.execute(f"MATCH (n:{table}) RETURN COUNT(*) AS cnt")
            count = res.get_next()[0] if res.has_next() else 0
            lines.append(f"  {table:<20} {count}")
        except Exception:  # noqa: BLE001
            lines.append(f"  {table:<20} (error)")

    lines.append("KUZU graph edge counts:")
    for table in rel_tables:
        try:
            res = conn.execute(f"MATCH ()-[r:{table}]->() RETURN COUNT(*) AS cnt")
            count = res.get_next()[0] if res.has_next() else 0
            lines.append(f"  {table:<20} {count}")
        except Exception:  # noqa: BLE001
            lines.append(f"  {table:<20} (error)")

    logger.info("\n".join(lines))
