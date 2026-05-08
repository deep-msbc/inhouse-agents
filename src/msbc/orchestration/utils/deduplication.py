"""
Artifact deduplication logic for Phase 2.

Reads the artifact_index built by artifact_index.py and identifies duplicate
artifacts across canonical modules. Produces:
  - A cleaned artifact_index with duplicates merged or flagged.
  - A dedupe_report with full audit trail of merge decisions and conflicts.

All deduplication is deterministic — no LLM calls.

Deduplication rules per artifact type:
  api_endpoints   — match by (method, normalized_path). Compatible schemas → merge.
                    Incompatible schemas → conflict.
  db_models       — match by normalized table_name. Compatible fields → merge (union).
                    Incompatible primary keys → conflict.
  enums           — match by normalized name. Subset chain → keep most complete.
                    Conflicting value semantics → conflict + recommended_canonical.
  business_rules  — match by Jaccard word-token similarity >= 0.80 → merge.
  screens         — kept as-is (screens are module-local; cross-module duplicates rare).
  workflows       — kept as-is (workflows are module-local narratives).

Conflict resolution priority (when a winner must be chosen):
  1. Prefer artifact from the module with more source_section_ids (more evidence).
  2. Prefer the artifact with more complete fields/values.
  3. If tied, prefer the first in document order (lower module index).
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# ── Similarity helpers ─────────────────────────────────────────────────────────

def _jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    """Jaccard similarity between two string sets. Returns 1.0 for two empty sets."""
    if not set_a and not set_b:
        return 1.0
    union = len(set_a | set_b)
    return len(set_a & set_b) / union if union else 0.0


def _field_names(fields: list[dict]) -> set[str]:
    """Extract normalized field name strings from a model fields list."""
    names: set[str] = set()
    for f in (fields or []):
        if isinstance(f, dict):
            n = f.get("name") or f.get("field_name") or ""
            if n:
                names.add(n.strip().lower())
    return names


def _merge_fields(
    primary: list[dict],
    secondary: list[dict],
) -> list[dict]:
    """
    Union of two field lists, deduplicated by normalized field name.
    Primary fields take precedence when both lists define the same name.
    """
    seen:   set[str]    = set()
    result: list[dict]  = []
    for field in primary + secondary:
        name = (field.get("name") or field.get("field_name") or "").strip().lower()
        if name and name not in seen:
            seen.add(name)
            result.append(field)
        elif not name:
            result.append(field)
    return result


def _pick_winner_by_evidence(group: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Choose the canonical artifact from a group using conflict resolution priority:
    1. Most source_section_ids (most evidence from the document).
    2. Most fields / most values (most complete definition).
    3. First in list order (document order via module ordering).
    """
    sorted_group = sorted(
        group,
        key=lambda s: (
            -len(s.get("source_chunk_ids") or []),
            -len(s.get("fields") or []) - len(s.get("values") or []),
        ),
    )
    winner = sorted_group[0]
    dupes  = sorted_group[1:]
    return winner, dupes


def _merged_sources(group: list[dict[str, Any]]) -> list[str]:
    """Collect the union of source_chunk_ids across all artifacts in a group."""
    seen: set[str]   = set()
    result: list[str] = []
    for sig in group:
        for sid in (sig.get("source_chunk_ids") or []):
            if sid not in seen:
                seen.add(sid)
                result.append(sid)
    return result


# ── API endpoint deduplication ────────────────────────────────────────────────

def _dedup_api_endpoints(
    sigs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Deduplicate API endpoint signatures by (method, normalized_path).

    Compatible schemas (field overlap >= 0.50 OR both have empty schema) → merge.
    Incompatible schemas → conflict.

    Returns:
        (canonical_sigs, decisions)
    """
    # Group by (method, normalized_path)
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for sig in sigs:
        key = (
            (sig.get("method") or "").upper(),
            sig.get("path") or "/",
        )
        groups.setdefault(key, []).append(sig)

    canonical:  list[dict[str, Any]] = []
    decisions:  list[dict[str, Any]] = []

    for (method, path), group in groups.items():
        if len(group) == 1:
            canonical.append(group[0])
            continue

        winner, dupes = _pick_winner_by_evidence(group)

        # Check schema compatibility — field name overlap
        winner_fields = _field_names(winner.get("fields") or [])
        all_compatible = True
        for dupe in dupes:
            dupe_fields = _field_names(dupe.get("fields") or [])
            if winner_fields and dupe_fields:
                sim = _jaccard_similarity(winner_fields, dupe_fields)
                if sim < 0.50:
                    all_compatible = False
                    break

        module_keys = ", ".join(dict.fromkeys(s["module_key"] for s in group))

        if all_compatible:
            merged_sig = dict(winner)
            merged_sig["source_chunk_ids"] = _merged_sources(group)
            # Merge request body fields from all duplicates
            all_fields = [f for s in group for f in (s.get("fields") or [])]
            if all_fields:
                merged_sig["fields"] = _merge_fields(
                    winner.get("fields") or [], all_fields
                )
            canonical.append(merged_sig)
            decisions.append({
                "artifact_type":          "api_endpoint",
                "canonical_artifact_id":  winner["artifact_id"],
                "duplicate_artifact_ids": [d["artifact_id"] for d in dupes],
                "action":                 "merge",
                "reason": (
                    f"{method} {path} appears in multiple modules "
                    f"({module_keys}) with compatible request schemas. "
                    f"Merged source references from all definitions."
                ),
                "confidence":    0.82,
                "merged_output": merged_sig,
                "needs_review":  False,
            })
        else:
            # Keep all — flag for human review
            canonical.extend(group)
            decisions.append({
                "artifact_type":          "api_endpoint",
                "canonical_artifact_id":  winner["artifact_id"],
                "duplicate_artifact_ids": [d["artifact_id"] for d in dupes],
                "action":                 "conflict",
                "reason": (
                    f"{method} {path} appears in multiple modules "
                    f"({module_keys}) with incompatible request schemas "
                    f"(field name overlap < 50%). Manual review required."
                ),
                "confidence":    0.70,
                "merged_output": None,
                "needs_review":  True,
            })

    return canonical, decisions


# ── DB model deduplication ────────────────────────────────────────────────────

def _dedup_db_models(
    sigs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Deduplicate DB model signatures by normalized table_name.

    Compatible primary keys (or both missing) → merge (field union).
    Incompatible primary keys → conflict.

    Returns:
        (canonical_sigs, decisions)
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for sig in sigs:
        key = sig.get("table_name") or sig.get("normalized_name") or "unknown_model"
        groups.setdefault(key, []).append(sig)

    canonical: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []

    for table_name, group in groups.items():
        if len(group) == 1:
            canonical.append(group[0])
            continue

        winner, dupes = _pick_winner_by_evidence(group)
        module_keys   = ", ".join(dict.fromkeys(s["module_key"] for s in group))

        # Check primary key compatibility
        winner_pks = {
            f for f in _field_names(winner.get("fields") or [])
            if "id" in f or "pk" in f or "key" in f
        }
        conflict = False
        for dupe in dupes:
            dupe_pks = {
                f for f in _field_names(dupe.get("fields") or [])
                if "id" in f or "pk" in f or "key" in f
            }
            if winner_pks and dupe_pks and not winner_pks.intersection(dupe_pks):
                conflict = True
                break

        if not conflict:
            all_fields    = [f for s in group for f in (s.get("fields") or [])]
            merged_fields = _merge_fields(winner.get("fields") or [], all_fields)
            merged_sig    = dict(winner)
            merged_sig["fields"]             = merged_fields
            merged_sig["source_chunk_ids"] = _merged_sources(group)
            merged_sig["raw"]                = dict(winner["raw"])
            merged_sig["raw"]["fields"]      = merged_fields
            canonical.append(merged_sig)
            decisions.append({
                "artifact_type":          "db_model",
                "canonical_artifact_id":  winner["artifact_id"],
                "duplicate_artifact_ids": [d["artifact_id"] for d in dupes],
                "action":                 "merge",
                "reason": (
                    f"DB model '{table_name}' appears in multiple modules "
                    f"({module_keys}) with compatible schemas. "
                    f"Merged {len(merged_fields)} field(s) from all definitions."
                ),
                "confidence":    0.88,
                "merged_output": merged_sig,
                "needs_review":  False,
            })
        else:
            canonical.extend(group)
            decisions.append({
                "artifact_type":          "db_model",
                "canonical_artifact_id":  winner["artifact_id"],
                "duplicate_artifact_ids": [d["artifact_id"] for d in dupes],
                "action":                 "conflict",
                "reason": (
                    f"DB model '{table_name}' has incompatible primary key definitions "
                    f"across modules: {module_keys}. Manual review required."
                ),
                "confidence":    0.75,
                "merged_output": None,
                "needs_review":  True,
            })

    return canonical, decisions


# ── Enum deduplication ────────────────────────────────────────────────────────

def _dedup_enums(
    sigs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Deduplicate enum signatures by normalized name.

    Subset chain (every pair is a subset of the other or one contains the other)
    → keep the most complete value set.
    Conflicting value semantics → conflict with recommended_canonical (union).

    Returns:
        (canonical_sigs, decisions)
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for sig in sigs:
        key = sig.get("normalized_name") or "unknown_enum"
        groups.setdefault(key, []).append(sig)

    canonical: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []

    for norm_name, group in groups.items():
        if len(group) == 1:
            canonical.append(group[0])
            continue

        value_sets = [frozenset(s.get("values") or []) for s in group]
        module_keys = ", ".join(dict.fromkeys(s["module_key"] for s in group))

        # Check subset chain: every pair (i, j) must satisfy vs_i ⊆ vs_j or vs_j ⊆ vs_i
        is_subset_chain = True
        for i in range(len(value_sets)):
            for j in range(len(value_sets)):
                if i == j:
                    continue
                if not (value_sets[i] <= value_sets[j] or value_sets[j] <= value_sets[i]):
                    is_subset_chain = False
                    break
            if not is_subset_chain:
                break

        if is_subset_chain:
            # Use the largest value set as canonical
            group_sorted  = sorted(group, key=lambda s: -len(s.get("values") or []))
            winner, dupes = group_sorted[0], group_sorted[1:]
            merged_sig    = dict(winner)
            merged_sig["source_chunk_ids"] = _merged_sources(group)
            canonical.append(merged_sig)
            decisions.append({
                "artifact_type":          "enum",
                "canonical_artifact_id":  winner["artifact_id"],
                "duplicate_artifact_ids": [d["artifact_id"] for d in dupes],
                "action":                 "merge",
                "reason": (
                    f"Enum '{norm_name}' appears in modules ({module_keys}) — "
                    f"all value sets are in a subset chain. "
                    f"Most complete set ({len(winner.get('values') or [])} values) chosen."
                ),
                "confidence":    0.85,
                "merged_output": merged_sig,
                "needs_review":  False,
            })
        else:
            # Conflicting value sets — recommend union and flag for review
            union_values = sorted({v for s in group for v in (s.get("values") or [])})
            winner, dupes = _pick_winner_by_evidence(group)
            canonical.extend(group)  # keep all pending human review
            decisions.append({
                "artifact_type":          "enum",
                "canonical_artifact_id":  winner["artifact_id"],
                "duplicate_artifact_ids": [d["artifact_id"] for d in dupes],
                "action":                 "conflict",
                "reason": (
                    f"Enum '{norm_name}' has conflicting value sets across modules "
                    f"({module_keys}): "
                    + " vs ".join(str(sorted(vs)) for vs in value_sets)
                ),
                "confidence":    0.70,
                "merged_output": None,
                "needs_review":  True,
                "recommended_canonical": union_values,
            })

    return canonical, decisions


# ── Business rule deduplication ────────────────────────────────────────────────

def _dedup_business_rules(
    sigs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Deduplicate business rules by normalized word-token Jaccard similarity.

    Two rules are considered duplicates if their normalized texts share >= 80%
    of word tokens. The rule with more source evidence is kept as canonical.

    Returns:
        (canonical_sigs, decisions)
    """
    if not sigs:
        return [], []

    def _word_set(text: str) -> set[str]:
        return set(re.findall(r"\w+", (text or "").lower()))

    canonical: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    used: set[int]                   = set()

    for i, sig_i in enumerate(sigs):
        if i in used:
            continue

        words_i    = _word_set(sig_i.get("normalized_name") or "")
        duplicates: list[dict[str, Any]] = []

        for j, sig_j in enumerate(sigs):
            if j <= i or j in used:
                continue
            words_j = _word_set(sig_j.get("normalized_name") or "")
            if _jaccard_similarity(words_i, words_j) >= 0.80:
                duplicates.append(sig_j)
                used.add(j)

        if duplicates:
            used.add(i)
            all_group = [sig_i] + duplicates
            winner, dupes = _pick_winner_by_evidence(all_group)
            merged_sig = dict(winner)
            merged_sig["source_chunk_ids"] = _merged_sources(all_group)
            canonical.append(merged_sig)
            decisions.append({
                "artifact_type":          "business_rule",
                "canonical_artifact_id":  winner["artifact_id"],
                "duplicate_artifact_ids": [d["artifact_id"] for d in dupes],
                "action":                 "merge",
                "reason": (
                    f"Business rule appears semantically equivalent (word Jaccard >= 0.80) "
                    f"across modules: "
                    f"{', '.join(dict.fromkeys(s['module_key'] for s in all_group))}. "
                    f"Canonical retained from '{winner['module_key']}'."
                ),
                "confidence":    0.78,
                "merged_output": merged_sig,
                "needs_review":  False,
            })
        else:
            canonical.append(sig_i)

    return canonical, decisions


# ── Self-edge removal (graph post-processing helper) ──────────────────────────

def remove_self_edges(
    edges: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Remove edges where from == to (self-referencing module dependencies).

    Called by finalize_node after the dependency graph is built.

    Returns:
        (filtered_edges, list_of_self_referencing_module_ids)
    """
    kept:    list[dict[str, Any]] = []
    removed: list[str]            = []
    for edge in (edges or []):
        from_id = edge.get("from", "")
        to_id   = edge.get("to",   "")
        if from_id and from_id == to_id:
            removed.append(from_id)
            logger.info(
                "remove_self_edges: removed self-referencing edge '%s' → '%s'.",
                from_id, to_id,
            )
        else:
            kept.append(edge)
    return kept, removed


# ── Main entry point ───────────────────────────────────────────────────────────

def run_deduplication(
    artifact_index: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """
    Run the full deduplication pass across all artifact types.

    Args:
        artifact_index: Output of build_artifact_index() — grouped ArtifactSignature dicts.

    Returns:
        (cleaned_artifact_index, dedupe_report)

    dedupe_report structure:
    {
        "merged_artifacts": [
            {
                "artifact_type":   "api_endpoint" | "db_model" | "enum" | "business_rule",
                "canonical_id":    str,
                "merged_from_ids": [str, ...],
                "reason":          str,
                "confidence":      float,
            },
            ...
        ],
        "conflicts": [
            {
                "artifact_type":        str,
                "canonical_id":         str,
                "conflicting_ids":      [str, ...],
                "reason":               str,
                "needs_review":         True,
                "recommended_canonical": list[str] | None,
            },
            ...
        ],
        "self_edges_removed": [],      # populated by finalize_node after graph build
        "summary": {
            "total_artifacts_before":  int,
            "total_artifacts_after":   int,
            "duplicate_groups_merged": int,
            "conflicts_flagged":       int,
            "self_edges_removed":      0,  # updated by finalize_node
        },
    }
    """
    total_before = sum(len(v) for v in artifact_index.values())

    # -- Deduplicate each artifact type
    api_canonical,   api_decisions   = _dedup_api_endpoints(
        artifact_index.get("api_endpoints") or []
    )
    model_canonical, model_decisions = _dedup_db_models(
        artifact_index.get("db_models") or []
    )
    enum_canonical,  enum_decisions  = _dedup_enums(
        artifact_index.get("enums") or []
    )
    rule_canonical,  rule_decisions  = _dedup_business_rules(
        artifact_index.get("business_rules") or []
    )

    # Screens and workflows are retained as-is: cross-module duplication is
    # intentional (each module has its own named screens) and cannot be resolved
    # without domain knowledge that only a human analyst can provide.
    screen_canonical   = list(artifact_index.get("screens") or [])
    workflow_canonical = list(artifact_index.get("workflows") or [])

    all_decisions: list[dict[str, Any]] = (
        api_decisions + model_decisions + enum_decisions + rule_decisions
    )

    cleaned_index: dict[str, list[dict[str, Any]]] = {
        "api_endpoints":  api_canonical,
        "db_models":      model_canonical,
        "enums":          enum_canonical,
        "business_rules": rule_canonical,
        "screens":        screen_canonical,
        "workflows":      workflow_canonical,
    }

    total_after      = sum(len(v) for v in cleaned_index.values())
    merge_decisions  = [d for d in all_decisions if d.get("action") == "merge"]
    conflict_decs    = [d for d in all_decisions if d.get("action") == "conflict"]

    dedupe_report: dict[str, Any] = {
        "merged_artifacts": [
            {
                "artifact_type":   d["artifact_type"],
                "canonical_id":    d["canonical_artifact_id"],
                "merged_from_ids": d["duplicate_artifact_ids"],
                "reason":          d["reason"],
                "confidence":      d["confidence"],
            }
            for d in merge_decisions
        ],
        "conflicts": [
            {
                "artifact_type":        d["artifact_type"],
                "canonical_id":         d["canonical_artifact_id"],
                "conflicting_ids":      d["duplicate_artifact_ids"],
                "reason":               d["reason"],
                "needs_review":         d.get("needs_review", True),
                "recommended_canonical": d.get("recommended_canonical"),
            }
            for d in conflict_decs
        ],
        # self_edges_removed is populated by finalize_node after the graph is built
        "self_edges_removed": [],
        "summary": {
            "total_artifacts_before":  total_before,
            "total_artifacts_after":   total_after,
            "duplicate_groups_merged": len(merge_decisions),
            "conflicts_flagged":       len(conflict_decs),
            "self_edges_removed":      0,
        },
    }

    logger.info(
        "run_deduplication: %d artifacts before → %d after. "
        "%d group(s) merged, %d conflict(s) flagged.",
        total_before,
        total_after,
        len(merge_decisions),
        len(conflict_decs),
    )
    return cleaned_index, dedupe_report
