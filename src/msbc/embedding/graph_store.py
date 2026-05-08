"""
KuzuStore — thin wrapper around an on-disk KUZU graph database.

Called by generation agent nodes inside the LangGraph workflow to perform
structured graph traversal queries that complement Qdrant vector search.

Design notes
------------
• This class only **reads** from the graph.  Writes are performed by
  ``graph_builder.build_graph()`` / ``graph_builder.rebuild_graph()``.
• ``query()`` returns rows as ``list[dict]`` with column names as keys —
  consistent with how other retrieval results are passed between agent nodes.
• All high-level helpers call ``query()`` internally; they are thin
  convenience wrappers that can be imported individually by agent nodes.
• No HTTP endpoint — retrieval is triggered inside LangGraph tool nodes.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import kuzu

from app.core.config import settings

logger = logging.getLogger(__name__)


class KuzuStore:
    """
    Read-only interface to the KUZU toolkit knowledge graph.

    Parameters
    ----------
    db_path : str, optional
        Path to the on-disk ``.kuzu`` directory.
        Defaults to ``settings.KUZU_DB_PATH``.
    """

    def __init__(self, db_path: str | None = None, read_only: bool = True) -> None:
        self._db_path = db_path or settings.KUZU_DB_PATH
        self._available = False
        self._db = None
        self._conn = None

        db_file = Path(self._db_path).resolve()
        self._db_path = str(db_file)
        if not db_file.exists():
            logger.warning(
                "KuzuStore: DB not found at '%s' — graph queries will return empty results. "
                "Run 'python scripts/build_graph.py' to build the graph.",
                self._db_path,
            )
            return

        self._db   = kuzu.Database(self._db_path, read_only=read_only)
        self._conn = kuzu.Connection(self._db)
        self._available = True
        logger.info("KuzuStore opened at '%s' (read_only=%s).", self._db_path, read_only)

    # ------------------------------------------------------------------
    # Generic query
    # ------------------------------------------------------------------

    def query(self, cypher: str) -> list[dict[str, Any]]:
        """
        Execute *cypher* and return all rows as a list of dicts.

        Each dict maps column name → value (Python native types).
        An empty list is returned when the query matches nothing.

        Parameters
        ----------
        cypher : str
            Read-only Cypher query string.

        Returns
        -------
        list[dict[str, Any]]
            One dict per result row; keys are the column aliases from the
            ``RETURN`` clause (e.g. ``"name"``, ``"description"``).

        Raises
        ------
        RuntimeError
            Wraps any KUZU runtime error with the offending query appended
            so callers can log it without losing context.
        """
        if not self._available:
            return []

        try:
            res = self._conn.execute(cypher)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"KUZU query failed: {exc}\nCypher: {cypher.strip()}"
            ) from exc

        columns = res.get_column_names()
        rows: list[dict[str, Any]] = []
        while res.has_next():
            row = res.get_next()
            rows.append(dict(zip(columns, row)))
        return rows

    # ------------------------------------------------------------------
    # High-level helpers (used by LangGraph agent nodes)
    # ------------------------------------------------------------------

    def get_component_internals(self, component_name: str) -> list[dict[str, Any]]:
        """
        Return the components that *component_name* internally uses
        (``InternallyUses`` edges).

        Answers: *"What does ConfigurableDashboard internally use?"*

        Parameters
        ----------
        component_name : str
            Exact component name, e.g. ``"ConfigurableDashboard"``.

        Returns
        -------
        list[dict]
            Each row: ``{name, description, component_type}``.
        """
        cypher = f"""
MATCH (c:Component {{name: '{_esc(component_name)}'}})
      -[:InternallyUses]->
      (u:Component)
RETURN u.name AS name,
       u.description AS description,
       u.component_type AS component_type
ORDER BY u.name
"""
        return self.query(cypher)

    def get_examples_by_features(
        self, feature_names: list[str]
    ) -> list[dict[str, Any]]:
        """
        Return examples that exhibit **all** of the requested features.

        Answers: *"Find examples with search + date filters"*

        Parameters
        ----------
        feature_names : list[str]
            Canonical feature flag names, e.g.
            ``["has_search", "has_filters"]``.

        Returns
        -------
        list[dict]
            Each row: ``{example_id, example_group, pattern,
            complexity, use_case, qdrant_chunk_ids}``.
        """
        if not feature_names:
            return []

        feat_list = "[" + ", ".join(f"'{_esc(f)}'" for f in feature_names) + "]"
        n_required = len(feature_names)

        cypher = f"""
MATCH (e:Example)-[:ExhibitsFeature]->(f:Feature)
WHERE f.name IN {feat_list}
WITH e, COUNT(f) AS matched
WHERE matched = {n_required}
RETURN e.example_id AS example_id,
       e.example_group AS example_group,
       e.pattern AS pattern,
       e.complexity AS complexity,
       e.use_case AS use_case,
       e.qdrant_chunk_ids AS qdrant_chunk_ids
ORDER BY e.example_id
"""
        return self.query(cypher)

    def get_component_types(self, component_name: str) -> list[dict[str, Any]]:
        """
        Return TypeDef nodes required by *component_name* (``UsesType`` edges).

        Answers: *"What config type does ConfigurableForm require?"*

        Parameters
        ----------
        component_name : str
            Exact component name, e.g. ``"ConfigurableForm"``.

        Returns
        -------
        list[dict]
            Each row: ``{name, description, required_fields, role}``.
        """
        cypher = f"""
MATCH (c:Component {{name: '{_esc(component_name)}'}})
      -[r:UsesType]->
      (t:TypeDef)
RETURN t.name AS name,
       t.description AS description,
       t.required_fields AS required_fields,
       r.role AS role
ORDER BY t.name
"""
        return self.query(cypher)

    def get_all_components(self) -> list[dict[str, Any]]:
        """
        Return every Component node — used for full component registry injection
        into agent context at the start of a generation workflow.

        Returns
        -------
        list[dict]
            Each row: ``{id, name, component_type, description,
            when_to_use, do_not_use_when}``.
        """
        cypher = """
MATCH (c:Component)
RETURN c.id AS id,
       c.name AS name,
       c.component_type AS component_type,
       c.description AS description,
       c.when_to_use AS when_to_use,
       c.do_not_use_when AS do_not_use_when
ORDER BY c.name
"""
        return self.query(cypher)

    def get_component_features(self, component_name: str) -> list[dict[str, Any]]:
        """
        Return Feature nodes exhibited by *component_name* (``ExhibitsFeature`` edges).

        Parameters
        ----------
        component_name : str
            Exact component name, e.g. ``"ConfigurableDashboard"``.

        Returns
        -------
        list[dict]
            Each row: ``{name, label}``.
        """
        cypher = f"""
MATCH (c:Component {{name: '{_esc(component_name)}'}})
      -[:ExhibitsFeature]->
      (f:Feature)
RETURN f.name AS name,
       f.label AS label
ORDER BY f.name
"""
        return self.query(cypher)

    def get_example_files(self, example_id: str) -> list[dict[str, Any]]:
        """
        Return all ExampleFile nodes belonging to *example_id* (``HasFile`` edges).

        Parameters
        ----------
        example_id : str
            Folder-level identifier, e.g. ``"Dashboard03"``.

        Returns
        -------
        list[dict]
            Each row: ``{file_name, file_role, file_path, qdrant_chunk_id}``.
        """
        cypher = f"""
MATCH (e:Example {{example_id: '{_esc(example_id)}'}})
      -[:HasFile]->
      (ef:ExampleFile)
RETURN ef.file_name AS file_name,
       ef.file_role AS file_role,
       ef.file_path AS file_path,
       ef.qdrant_chunk_id AS qdrant_chunk_id
ORDER BY ef.file_name
"""
        return self.query(cypher)

    def get_packages(self) -> list[dict[str, Any]]:
        """
        Return all Package nodes.

        Returns
        -------
        list[dict]
            Each row: ``{name, import_path, description}``.
        """
        cypher = """
MATCH (p:Package)
RETURN p.name AS name,
       p.import_path AS import_path,
       p.description AS description
ORDER BY p.name
"""
        return self.query(cypher)

    # ------------------------------------------------------------------
    # Write helpers (called by ingestors to keep graph in sync)
    # ------------------------------------------------------------------

    def update_example_chunk_ids(
        self, example_id: str, chunk_ids: list[str]
    ) -> None:
        """
        Write the Qdrant point UUIDs for *example_id* back into the KUZU
        graph so the generation agent can resolve chunk IDs without an
        extra Qdrant filter query.

        Called by ``examples_ingestor.ingest_examples()`` after every
        successful upsert, so the KUZU graph stays in sync with Qdrant.

        Parameters
        ----------
        example_id : str
            Folder-level identifier, e.g. ``"Dashboard03"``.
        chunk_ids : list[str]
            List of Qdrant point UUID strings (all chunks + summary chunk).
        """
        id_list = _cypher_str_list(chunk_ids)
        cypher = (
            f"MATCH (e:Example {{example_id: '{_esc(example_id)}'}}) "
            f"SET e.qdrant_chunk_ids = {id_list}"
        )
        if not self._available:
            logger.warning("KuzuStore unavailable — skipping qdrant_chunk_ids update for '%s'.", example_id)
            return

        try:
            self._conn.execute(cypher)
            logger.debug(
                "KUZU: updated qdrant_chunk_ids for '%s' (%d IDs).",
                example_id, len(chunk_ids),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "KUZU: failed to update qdrant_chunk_ids for '%s': %s",
                example_id, exc,
            )

    # ------------------------------------------------------------------
    # Retrieval helpers for Phase 3 (Code Generation agent)
    # ------------------------------------------------------------------

    def get_examples_for_generation(
        self,
        pattern: str,
        feature_names: list[str] | None = None,
        field_types: list[str] | None = None,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        """
        Filter-then-return the best matching examples for a generation request.

        This is the primary retrieval helper for the Phase 3 code generation
        agent node.  It applies hard filters (pattern match, feature match)
        before returning results — so the LLM only sees relevant examples,
        never mismatched ones.

        Strategy
        --------
        1. Filter by ``pattern`` (mandatory — most selective filter).
        2. Filter by ``feature_names`` — example must exhibit ALL listed features.
        3. Filter by ``field_types`` — example must exhibit ALL listed field types.
        4. Return up to *limit* results, ordered by complexity descending
           (complex examples cover more features and are better templates).

        Parameters
        ----------
        pattern : str
            Component pattern to match, e.g. ``"ConfigurableDashboard"`` or
            ``"ConfigurableForm"``.
        feature_names : list[str], optional
            Feature flags the example must exhibit, e.g.
            ``["has_search", "has_filters"]``.  Omit or pass ``[]`` to skip.
        field_types : list[str], optional
            Form field types the example must support, e.g.
            ``["fileUpload", "date"]``.  Omit or pass ``[]`` to skip.
        limit : int
            Maximum number of examples to return.  Default 3.

        Returns
        -------
        list[dict]
            Each row: ``{example_id, example_group, pattern, complexity,
            use_case, qdrant_chunk_ids}``.  Ordered complex → simple.
        """
        feature_names = feature_names or []
        field_types = field_types or []

        # ── Build WHERE / WITH clauses incrementally ──────────────────────────

        # Base: match pattern
        cypher_parts = [
            f"MATCH (e:Example {{pattern: '{_esc(pattern)}'}})",
        ]

        if feature_names:
            feat_list = "[" + ", ".join(f"'{_esc(f)}'" for f in feature_names) + "]"
            n_feat = len(feature_names)
            cypher_parts += [
                "WITH e",
                "MATCH (e)-[:ExhibitsFeature]->(f:Feature)",
                f"WHERE f.name IN {feat_list}",
                f"WITH e, COUNT(f) AS feat_match WHERE feat_match = {n_feat}",
            ]

        if field_types:
            ft_list = "[" + ", ".join(f"'{_esc(t)}'" for t in field_types) + "]"
            n_ft = len(field_types)
            cypher_parts += [
                "WITH e",
                "MATCH (e)-[:ExhibitsFieldType]->(ft:FieldType)",
                f"WHERE ft.name IN {ft_list}",
                f"WITH e, COUNT(ft) AS ft_match WHERE ft_match = {n_ft}",
            ]

        # Return + order by complexity (complex > medium > simple)
        cypher_parts += [
            "RETURN DISTINCT",
            "  e.example_id AS example_id,",
            "  e.example_group AS example_group,",
            "  e.pattern AS pattern,",
            "  e.complexity AS complexity,",
            "  e.use_case AS use_case,",
            "  e.qdrant_chunk_ids AS qdrant_chunk_ids",
            # KUZU does not support CASE in ORDER BY — sort client-side
            f"LIMIT {limit}",
        ]

        cypher = "\n".join(cypher_parts)
        rows = self.query(cypher)

        # Sort client-side: complex → medium → simple
        _rank = {"complex": 2, "medium": 1, "simple": 0}
        rows.sort(key=lambda r: _rank.get(r.get("complexity", ""), 0), reverse=True)
        return rows

    def close(self) -> None:
        """Close the KUZU connection (optional — GC handles cleanup)."""
        try:
            self._conn.close()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Internal helpers (mirror graph_builder equivalents — no cross-import)
# ---------------------------------------------------------------------------

def _esc(s: str) -> str:
    """Escape single quotes in *s* for safe inline Cypher string literals."""
    return s.replace("'", "\\'")


def _cypher_str_list(items: list[str]) -> str:
    """Render a Python list of strings as a KUZU STRING[] literal."""
    inner = ", ".join(f"'{_esc(i)}'" for i in items)
    return f"[{inner}]"
