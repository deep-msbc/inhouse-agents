import asyncio
import sys
import types
import unittest

stub_openai_client = types.ModuleType("src.msbc.llm.clients.openai_client")
stub_openai_client.call_llm_with_schema = None
stub_openai_client.count_tokens = lambda text: len((text or "").split())
stub_openai_client.merge_usage = lambda usages: usages
sys.modules.setdefault("src.msbc.llm.clients.openai_client", stub_openai_client)

stub_config = types.ModuleType("src.msbc.config")
stub_config.TOTAL_INPUT_TOKEN_LIMIT = 8000
stub_config.PROMPT_MAX_TOKENS = 1500
stub_config.MODULE_EXTRACTION_TIMEOUT = 900
stub_config.MODULE_BATCH_SIZE = 3
sys.modules.setdefault("src.msbc.config", stub_config)

from src.msbc.orchestration.nodes.node_definitions import (
    artifact_deduplication_node,
    artifact_index_node,
)
from src.msbc.orchestration.utils.artifact_index import build_artifact_index
from src.msbc.orchestration.utils.deduplication import run_deduplication
from src.msbc.orchestration.utils.heading_normalization import normalize_heading_hierarchy
from src.msbc.utils.extractors.docx_extractor import _numbered_section_level as docx_numbered_section_level
from src.msbc.utils.extractors.pdf_extractor import _numbered_section_level as pdf_numbered_section_level


# ── Utility: Build a minimal ModuleResult dict ────────────────────────────────

def _make_result(
    module_key: str,
    module_name: str,
    *,
    mode: str = "both",
    source_chunk_ids: list[str] | None = None,
    api_endpoints: list[dict] | None = None,
    models: list[dict] | None = None,
    enums: list[dict] | None = None,
    business_rules: list | None = None,
    screens: list[dict] | None = None,
    workflows: list | None = None,
) -> dict:
    """Build a minimal ModuleResult dict for use in tests."""
    if source_chunk_ids is None:
        source_chunk_ids = ["chunk_001"]

    if mode == "frontend":
        module_payload = {
            "enums":          enums or [],
            "business_rules": business_rules or [],
            "screens":        screens or [],
            "workflows":      workflows or [],
        }
    elif mode == "backend":
        module_payload = {
            "api_endpoints":  api_endpoints or [],
            "models":         models or [],
            "business_logic": business_rules or [],
            "workflows":      workflows or [],
        }
    else:  # both
        module_payload = {
            "frontend": {
                "enums":          enums or [],
                "business_rules": business_rules or [],
                "screens":        screens or [],
                "workflows":      workflows or [],
            },
            "backend": {
                "api_endpoints":  api_endpoints or [],
                "models":         models or [],
                "business_logic": business_rules or [],
                "workflows":      workflows or [],
            },
        }

    return {
        "module_key":      module_key,
        "module_name":     module_name,
        "source_chunk_ids": source_chunk_ids,
        "extraction":      {"module": module_payload},
        "summary":         {"module_name": module_name},
        "usage":           [],
    }


# ── Heading normalization tests (Phase 1 utility — kept) ─────────────────────

class HeadingNormalizationTests(unittest.TestCase):
    def test_normalization_preserves_repeated_headings_but_removes_noise(self) -> None:
        headings = [
            {"level": 0, "text": "Production Tracking"},
            {"level": 3, "text": "Purpose"},
            {"level": 3, "text": "Purpose"},
            {"level": 3, "text": "Section Title: Ignore Me"},
            {"level": 3, "text": "Batch History"},
        ]

        cleaned = normalize_heading_hierarchy(headings)

        self.assertEqual(
            cleaned,
            [
                {"level": 1, "text": "Production Tracking"},
                {"level": 3, "text": "Purpose"},
                {"level": 3, "text": "Batch History"},
            ],
        )

    def test_numbered_heading_depth_is_preserved(self) -> None:
        self.assertEqual(docx_numbered_section_level("8. Production Tracking"), 2)
        self.assertEqual(docx_numbered_section_level("8.1 Batch Tracking"), 3)
        self.assertEqual(pdf_numbered_section_level("8.1.1 Save Logic"), 4)


# ── Phase 2: Artifact Index tests ─────────────────────────────────────────────

class ArtifactIndexTests(unittest.TestCase):
    """Tests for build_artifact_index (src/msbc/orchestration/utils/artifact_index.py)."""

    def test_api_endpoints_indexed_from_backend_mode(self) -> None:
        results = [
            _make_result(
                "job_tracking", "Job Tracking",
                mode="backend",
                api_endpoints=[
                    {"method": "GET", "path": "/jobs", "name": "List Jobs"},
                    {"method": "POST", "path": "/jobs", "name": "Create Job"},
                ],
            )
        ]
        index = build_artifact_index(results, mode="backend")
        self.assertEqual(len(index["api_endpoints"]), 2)
        methods = {s["method"] for s in index["api_endpoints"]}
        self.assertIn("GET", methods)
        self.assertIn("POST", methods)

    def test_db_models_indexed_from_backend_mode(self) -> None:
        results = [
            _make_result(
                "inventory", "Inventory",
                mode="backend",
                models=[
                    {"name": "StockItem", "table_name": "stock_item", "fields": [
                        {"name": "id"}, {"name": "quantity"},
                    ]},
                ],
            )
        ]
        index = build_artifact_index(results, mode="backend")
        self.assertEqual(len(index["db_models"]), 1)
        self.assertEqual(index["db_models"][0]["table_name"], "stock_item")

    def test_enums_indexed_from_frontend_mode(self) -> None:
        results = [
            _make_result(
                "production", "Production",
                mode="frontend",
                enums=[{"name": "ProcessStatus", "values": ["Pending", "Active", "Done"]}],
            )
        ]
        index = build_artifact_index(results, mode="frontend")
        self.assertEqual(len(index["enums"]), 1)
        self.assertEqual(index["enums"][0]["name"], "ProcessStatus")
        self.assertEqual(index["enums"][0]["values"], ["Pending", "Active", "Done"])

    def test_screens_indexed_from_frontend_mode(self) -> None:
        results = [
            _make_result(
                "dashboard", "Dashboard",
                mode="frontend",
                screens=[{"name": "Dashboard Screen", "type": "grid"}],
            )
        ]
        index = build_artifact_index(results, mode="frontend")
        self.assertEqual(len(index["screens"]), 1)
        self.assertEqual(index["screens"][0]["name"], "Dashboard Screen")

    def test_both_mode_indexes_frontend_and_backend_artifacts(self) -> None:
        results = [
            _make_result(
                "orders", "Orders",
                mode="both",
                api_endpoints=[{"method": "GET", "path": "/orders"}],
                enums=[{"name": "OrderStatus", "values": ["Open", "Closed"]}],
                screens=[{"name": "Orders List"}],
            )
        ]
        index = build_artifact_index(results, mode="both")
        self.assertEqual(len(index["api_endpoints"]), 1)
        self.assertEqual(len(index["enums"]), 1)
        self.assertEqual(len(index["screens"]), 1)

    def test_source_chunk_ids_passed_through_to_signatures(self) -> None:
        results = [
            _make_result(
                "billing", "Billing",
                mode="backend",
                source_chunk_ids=["chunk_003", "chunk_004"],
                api_endpoints=[{"method": "GET", "path": "/invoices"}],
            )
        ]
        index = build_artifact_index(results, mode="backend")
        sig = index["api_endpoints"][0]
        self.assertIn("chunk_003", sig["source_chunk_ids"])
        self.assertIn("chunk_004", sig["source_chunk_ids"])

    def test_missing_module_key_falls_back_to_normalized_name(self) -> None:
        result = _make_result("", "My Module", mode="backend")
        result["module_key"] = ""
        index = build_artifact_index([result], mode="backend")
        # Should not raise; index keys are all present
        self.assertIn("api_endpoints", index)

    def test_empty_results_returns_empty_index(self) -> None:
        index = build_artifact_index([], mode="both")
        self.assertEqual(index["api_endpoints"], [])
        self.assertEqual(index["db_models"], [])

    def test_business_rules_indexed_from_both_mode(self) -> None:
        results = [
            _make_result(
                "stock", "Stock",
                mode="both",
                business_rules=["Quantity cannot be negative.", "Reorder when stock < 10."],
            )
        ]
        index = build_artifact_index(results, mode="both")
        # backend path: business_logic
        self.assertGreaterEqual(len(index["business_rules"]), 2)

    def test_workflows_indexed_from_backend_mode(self) -> None:
        results = [
            _make_result(
                "dispatch", "Dispatch",
                mode="backend",
                workflows=[{"name": "Dispatch Flow", "steps": ["Pick", "Pack", "Ship"]}],
            )
        ]
        index = build_artifact_index(results, mode="backend")
        self.assertEqual(len(index["workflows"]), 1)
        self.assertEqual(index["workflows"][0]["name"], "Dispatch Flow")


# ── Phase 2: artifact_index_node (LangGraph node wrapper) tests ───────────────

class ArtifactIndexNodeTests(unittest.TestCase):
    """Tests for artifact_index_node in node_definitions.py."""

    def test_node_returns_populated_artifact_index(self) -> None:
        state = {
            "results": [
                _make_result(
                    "tracking", "Tracking",
                    mode="backend",
                    api_endpoints=[{"method": "GET", "path": "/tracks"}],
                    models=[{"name": "Track", "table_name": "track", "fields": []}],
                )
            ],
            "mode": "backend",
        }
        result = artifact_index_node(state)
        index = result["artifact_index"]
        self.assertEqual(len(index.get("api_endpoints", [])), 1)
        self.assertEqual(len(index.get("db_models", [])), 1)

    def test_node_returns_empty_index_when_no_results(self) -> None:
        state = {"results": [], "mode": "both"}
        result = artifact_index_node(state)
        self.assertEqual(result["artifact_index"], {})

    def test_node_handles_missing_results_key(self) -> None:
        state = {"mode": "frontend"}
        result = artifact_index_node(state)
        self.assertEqual(result["artifact_index"], {})


# ── Phase 2: run_deduplication (utility) tests ────────────────────────────────

class DeduplicationUtilsTests(unittest.TestCase):
    """Tests for run_deduplication (src/msbc/orchestration/utils/deduplication.py)."""

    def _make_endpoint_sig(self, method: str, path: str, module_key: str, fields=None) -> dict:
        from src.msbc.orchestration.utils.artifact_index import normalize_path
        norm = normalize_path(path)
        return {
            "artifact_id":     f"api_endpoint__{module_key}__{method.lower()}_{norm}",
            "artifact_type":   "api_endpoint",
            "module_key":      module_key,
            "name":            f"{method} {path}",
            "normalized_name": f"{method}_{norm}",
            "method":          method,
            "path":            norm,
            "table_name":      None,
            "fields":          fields or [],
            "values":          [],
            "source_chunk_ids": ["chunk_001"],
            "raw":             {},
        }

    def _make_model_sig(self, table_name: str, module_key: str, fields=None, pks=None) -> dict:
        from src.msbc.orchestration.utils.artifact_index import normalize_name
        return {
            "artifact_id":     f"db_model__{module_key}__{normalize_name(table_name)}",
            "artifact_type":   "db_model",
            "module_key":      module_key,
            "name":            table_name,
            "normalized_name": normalize_name(table_name),
            "method":          None,
            "path":            None,
            "table_name":      normalize_name(table_name),
            "fields":          fields or pks or [],
            "values":          [],
            "source_chunk_ids": ["chunk_001"],
            "raw":             {},
        }

    def _make_enum_sig(self, name: str, module_key: str, values: list[str]) -> dict:
        from src.msbc.orchestration.utils.artifact_index import normalize_name
        norm = normalize_name(name)
        return {
            "artifact_id":     f"enum__{module_key}__{norm}",
            "artifact_type":   "enum",
            "module_key":      module_key,
            "name":            name,
            "normalized_name": norm,
            "method":          None,
            "path":            None,
            "table_name":      None,
            "fields":          [],
            "values":          values,
            "source_chunk_ids": ["chunk_001"],
            "raw":             {},
        }

    def _make_rule_sig(self, text: str, module_key: str) -> dict:
        from src.msbc.orchestration.utils.artifact_index import normalize_rule_text
        norm = normalize_rule_text(text)
        return {
            "artifact_id":     f"business_rule__{module_key}__r0_{norm[:20]}",
            "artifact_type":   "business_rule",
            "module_key":      module_key,
            "name":            text[:80],
            "normalized_name": norm,
            "method":          None,
            "path":            None,
            "table_name":      None,
            "fields":          [],
            "values":          [],
            "source_chunk_ids": ["chunk_001"],
            "raw":             {"text": text},
        }

    # ── API endpoint deduplication ─────────────────────────────────────────────

    def test_identical_endpoints_from_two_modules_are_merged(self) -> None:
        sigs = [
            self._make_endpoint_sig("GET", "/jobs", "module_a"),
            self._make_endpoint_sig("GET", "/jobs", "module_b"),
        ]
        cleaned, report = run_deduplication({"api_endpoints": sigs, "db_models": [],
                                              "enums": [], "business_rules": [],
                                              "screens": [], "workflows": []})
        self.assertEqual(len(cleaned["api_endpoints"]), 1)
        self.assertEqual(len(report["merged_artifacts"]), 1)
        self.assertEqual(report["merged_artifacts"][0]["artifact_type"], "api_endpoint")

    def test_endpoint_schema_conflict_is_flagged(self) -> None:
        sigs = [
            self._make_endpoint_sig("POST", "/jobs", "mod_a",
                                    fields=[{"name": "job_no"}, {"name": "status"}]),
            self._make_endpoint_sig("POST", "/jobs", "mod_b",
                                    fields=[{"name": "quantity"}, {"name": "worker"}]),
        ]
        cleaned, report = run_deduplication({"api_endpoints": sigs, "db_models": [],
                                              "enums": [], "business_rules": [],
                                              "screens": [], "workflows": []})
        # Both kept, flagged as conflict
        self.assertEqual(len(cleaned["api_endpoints"]), 2)
        self.assertEqual(len(report["conflicts"]), 1)
        self.assertTrue(report["conflicts"][0]["needs_review"])

    def test_unique_endpoints_are_not_merged(self) -> None:
        sigs = [
            self._make_endpoint_sig("GET", "/jobs", "mod_a"),
            self._make_endpoint_sig("GET", "/batches", "mod_b"),
        ]
        cleaned, report = run_deduplication({"api_endpoints": sigs, "db_models": [],
                                              "enums": [], "business_rules": [],
                                              "screens": [], "workflows": []})
        self.assertEqual(len(cleaned["api_endpoints"]), 2)
        self.assertEqual(len(report["merged_artifacts"]), 0)

    # ── DB model deduplication ─────────────────────────────────────────────────

    def test_same_model_in_two_modules_is_merged(self) -> None:
        sigs = [
            self._make_model_sig("StockItem", "inventory",
                                  fields=[{"name": "id"}, {"name": "quantity"}]),
            self._make_model_sig("StockItem", "warehouse",
                                  fields=[{"name": "id"}, {"name": "location"}]),
        ]
        cleaned, report = run_deduplication({"api_endpoints": [], "db_models": sigs,
                                              "enums": [], "business_rules": [],
                                              "screens": [], "workflows": []})
        self.assertEqual(len(cleaned["db_models"]), 1)
        self.assertGreaterEqual(len(cleaned["db_models"][0]["fields"]), 2)
        self.assertEqual(report["merged_artifacts"][0]["artifact_type"], "db_model")

    def test_model_pk_conflict_is_flagged(self) -> None:
        sigs = [
            self._make_model_sig("Job", "mod_a",
                                  fields=[{"name": "job_id"}]),
            self._make_model_sig("Job", "mod_b",
                                  fields=[{"name": "order_key"}]),
        ]
        cleaned, report = run_deduplication({"api_endpoints": [], "db_models": sigs,
                                              "enums": [], "business_rules": [],
                                              "screens": [], "workflows": []})
        self.assertEqual(len(cleaned["db_models"]), 2)
        self.assertEqual(len(report["conflicts"]), 1)

    # ── Enum deduplication ─────────────────────────────────────────────────────

    def test_enum_subset_chain_keeps_largest_value_set(self) -> None:
        sigs = [
            self._make_enum_sig("ProcessStatus", "mod_a", ["Pending", "Active"]),
            self._make_enum_sig("ProcessStatus", "mod_b", ["Pending", "Active", "Done"]),
        ]
        cleaned, report = run_deduplication({"api_endpoints": [], "db_models": [],
                                              "enums": sigs, "business_rules": [],
                                              "screens": [], "workflows": []})
        self.assertEqual(len(cleaned["enums"]), 1)
        self.assertIn("Done", cleaned["enums"][0]["values"])
        self.assertEqual(report["merged_artifacts"][0]["artifact_type"], "enum")

    def test_enum_value_conflict_is_flagged(self) -> None:
        sigs = [
            self._make_enum_sig("OrderStatus", "mod_a", ["Open", "Closed"]),
            self._make_enum_sig("OrderStatus", "mod_b", ["Draft", "Approved"]),
        ]
        cleaned, report = run_deduplication({"api_endpoints": [], "db_models": [],
                                              "enums": sigs, "business_rules": [],
                                              "screens": [], "workflows": []})
        self.assertEqual(len(cleaned["enums"]), 2)
        self.assertEqual(len(report["conflicts"]), 1)
        conflict = report["conflicts"][0]
        self.assertEqual(conflict["artifact_type"], "enum")
        self.assertTrue(conflict["needs_review"])

    # ── Business rule deduplication ────────────────────────────────────────────

    def test_semantically_equivalent_rules_are_merged(self) -> None:
        rule_text_a = "Remaining Quantity = Total Quantity - Used Quantity"
        rule_text_b = "Remaining quantity = total quantity - used quantity"
        sigs = [
            self._make_rule_sig(rule_text_a, "mod_a"),
            self._make_rule_sig(rule_text_b, "mod_b"),
        ]
        cleaned, report = run_deduplication({"api_endpoints": [], "db_models": [],
                                              "enums": [], "business_rules": sigs,
                                              "screens": [], "workflows": []})
        self.assertEqual(len(cleaned["business_rules"]), 1)
        self.assertEqual(len(report["merged_artifacts"]), 1)

    def test_distinct_rules_are_not_merged(self) -> None:
        sigs = [
            self._make_rule_sig("Quantity cannot be negative.", "mod_a"),
            self._make_rule_sig("All dispatch records must have a valid job reference.", "mod_b"),
        ]
        cleaned, report = run_deduplication({"api_endpoints": [], "db_models": [],
                                              "enums": [], "business_rules": sigs,
                                              "screens": [], "workflows": []})
        self.assertEqual(len(cleaned["business_rules"]), 2)
        self.assertEqual(len(report["merged_artifacts"]), 0)

    # ── Summary counts ─────────────────────────────────────────────────────────

    def test_dedupe_report_summary_counts_are_accurate(self) -> None:
        index = {
            "api_endpoints": [
                self._make_endpoint_sig("GET", "/items", "mod_a"),
                self._make_endpoint_sig("GET", "/items", "mod_b"),
            ],
            "db_models":      [],
            "enums":          [],
            "business_rules": [],
            "screens":        [],
            "workflows":      [],
        }
        _, report = run_deduplication(index)
        self.assertEqual(report["summary"]["total_artifacts_before"], 2)
        self.assertEqual(report["summary"]["total_artifacts_after"], 1)
        self.assertEqual(report["summary"]["duplicate_groups_merged"], 1)
        self.assertEqual(report["summary"]["conflicts_flagged"], 0)

    def test_no_duplicates_leaves_index_unchanged(self) -> None:
        index = {
            "api_endpoints": [
                self._make_endpoint_sig("GET", "/jobs", "mod_a"),
                self._make_endpoint_sig("POST", "/batches", "mod_b"),
            ],
            "db_models":      [],
            "enums":          [],
            "business_rules": [],
            "screens":        [],
            "workflows":      [],
        }
        cleaned, report = run_deduplication(index)
        self.assertEqual(len(cleaned["api_endpoints"]), 2)
        self.assertEqual(report["summary"]["duplicate_groups_merged"], 0)


# ── Phase 2: artifact_deduplication_node (LangGraph node wrapper) tests ───────

class ArtifactDeduplicationNodeTests(unittest.TestCase):
    """Tests for artifact_deduplication_node in node_definitions.py."""

    def _endpoint_sig(self, method: str, path: str, module_key: str) -> dict:
        from src.msbc.orchestration.utils.artifact_index import normalize_path
        norm = normalize_path(path)
        return {
            "artifact_id":     f"api_endpoint__{module_key}__{method.lower()}_{norm}",
            "artifact_type":   "api_endpoint",
            "module_key":      module_key,
            "name":            f"{method} {path}",
            "normalized_name": f"{method}_{norm}",
            "method":          method,
            "path":            norm,
            "table_name":      None,
            "fields":          [],
            "values":          [],
            "source_chunk_ids": ["chunk_001"],
            "raw":             {},
        }

    def test_node_deduplicates_identical_endpoints(self) -> None:
        artifact_index = {
            "api_endpoints": [
                self._endpoint_sig("GET", "/jobs", "mod_a"),
                self._endpoint_sig("GET", "/jobs", "mod_b"),
            ],
            "db_models": [], "enums": [], "business_rules": [],
            "screens": [], "workflows": [],
        }
        state = {"artifact_index": artifact_index}
        result = artifact_deduplication_node(state)

        self.assertIn("artifact_index", result)
        self.assertIn("dedupe_report", result)
        self.assertEqual(len(result["artifact_index"]["api_endpoints"]), 1)
        self.assertEqual(result["dedupe_report"]["summary"]["duplicate_groups_merged"], 1)

    def test_node_returns_empty_report_when_no_artifact_index(self) -> None:
        state = {"artifact_index": {}}
        result = artifact_deduplication_node(state)
        self.assertEqual(result["artifact_index"], {})
        report = result["dedupe_report"]
        self.assertEqual(report["summary"]["total_artifacts_before"], 0)
        self.assertEqual(report["merged_artifacts"], [])
        self.assertEqual(report["conflicts"], [])

    def test_node_handles_missing_artifact_index_key(self) -> None:
        state = {}
        result = artifact_deduplication_node(state)
        self.assertIn("dedupe_report", result)

    def test_node_flags_conflicts_in_report(self) -> None:
        artifact_index = {
            "api_endpoints": [],
            "db_models": [],
            "enums": [
                {
                    "artifact_id":     "enum__mod_a__order_status",
                    "artifact_type":   "enum",
                    "module_key":      "mod_a",
                    "name":            "OrderStatus",
                    "normalized_name": "order_status",
                    "method":          None,
                    "path":            None,
                    "table_name":      None,
                    "fields":          [],
                    "values":          ["Open", "Closed"],
                    "source_chunk_ids": ["chunk_001"],
                    "raw":             {},
                },
                {
                    "artifact_id":     "enum__mod_b__order_status",
                    "artifact_type":   "enum",
                    "module_key":      "mod_b",
                    "name":            "OrderStatus",
                    "normalized_name": "order_status",
                    "method":          None,
                    "path":            None,
                    "table_name":      None,
                    "fields":          [],
                    "values":          ["Draft", "Approved"],
                    "source_chunk_ids": ["chunk_002"],
                    "raw":             {},
                },
            ],
            "business_rules": [], "screens": [], "workflows": [],
        }
        state = {"artifact_index": artifact_index}
        result = artifact_deduplication_node(state)
        report = result["dedupe_report"]
        self.assertEqual(len(report["conflicts"]), 1)
        self.assertEqual(report["conflicts"][0]["artifact_type"], "enum")
        self.assertTrue(report["conflicts"][0]["needs_review"])


# ── Phase 2: End-to-end artifact pipeline tests ───────────────────────────────

class ArtifactPipelineEndToEndTests(unittest.TestCase):
    """Tests covering the full index → dedup → report pipeline."""

    def test_full_pipeline_produces_deduplication_report(self) -> None:
        results = [
            _make_result(
                "job_tracking", "Job Tracking",
                mode="both",
                source_chunk_ids=["chunk_001"],
                api_endpoints=[{"method": "GET", "path": "/jobs"}],
                enums=[{"name": "JobStatus", "values": ["Open", "Closed"]}],
            ),
            _make_result(
                "batch_tracking", "Batch Tracking",
                mode="both",
                source_chunk_ids=["chunk_002"],
                api_endpoints=[{"method": "GET", "path": "/jobs"}],  # duplicate endpoint
                enums=[{"name": "JobStatus", "values": ["Open", "Closed", "Archived"]}],
            ),
        ]
        index = build_artifact_index(results, mode="both")
        cleaned, report = run_deduplication(index)

        # Duplicate GET /jobs should be merged
        self.assertEqual(len(cleaned["api_endpoints"]), 1)
        # JobStatus subset chain → merged
        self.assertEqual(len(cleaned["enums"]), 1)
        self.assertIn("Archived", cleaned["enums"][0]["values"])
        self.assertGreaterEqual(report["summary"]["duplicate_groups_merged"], 1)
        self.assertEqual(report["summary"]["conflicts_flagged"], 0)

    def test_full_pipeline_preserves_screens_and_workflows_as_is(self) -> None:
        results = [
            _make_result(
                "mod_a", "Module A",
                mode="frontend",
                screens=[{"name": "Grid Screen"}],
                workflows=[{"name": "Approval Flow"}],
            ),
            _make_result(
                "mod_b", "Module B",
                mode="frontend",
                screens=[{"name": "Grid Screen"}],  # same screen name — kept separate
                workflows=[{"name": "Dispatch Flow"}],
            ),
        ]
        index = build_artifact_index(results, mode="frontend")
        cleaned, _ = run_deduplication(index)

        # Screens and workflows are never merged — both retained
        self.assertEqual(len(cleaned["screens"]), 2)
        self.assertEqual(len(cleaned["workflows"]), 2)

    def test_deduplication_report_has_required_keys(self) -> None:
        index = {
            "api_endpoints": [], "db_models": [], "enums": [],
            "business_rules": [], "screens": [], "workflows": [],
        }
        _, report = run_deduplication(index)
        required = {"merged_artifacts", "conflicts", "self_edges_removed", "summary"}
        self.assertTrue(required.issubset(report.keys()))
        summary_keys = {"total_artifacts_before", "total_artifacts_after",
                        "duplicate_groups_merged", "conflicts_flagged", "self_edges_removed"}
        self.assertTrue(summary_keys.issubset(report["summary"].keys()))

    def test_source_chunk_ids_merged_on_deduplication(self) -> None:
        from src.msbc.orchestration.utils.artifact_index import normalize_path
        norm = normalize_path("/jobs")
        sigs = [
            {
                "artifact_id":     "api_endpoint__mod_a__get__jobs",
                "artifact_type":   "api_endpoint",
                "module_key":      "mod_a",
                "name":            "GET /jobs",
                "normalized_name": f"GET_{norm}",
                "method":          "GET",
                "path":            norm,
                "table_name":      None,
                "fields":          [],
                "values":          [],
                "source_chunk_ids": ["chunk_001"],
                "raw":             {},
            },
            {
                "artifact_id":     "api_endpoint__mod_b__get__jobs",
                "artifact_type":   "api_endpoint",
                "module_key":      "mod_b",
                "name":            "GET /jobs",
                "normalized_name": f"GET_{norm}",
                "method":          "GET",
                "path":            norm,
                "table_name":      None,
                "fields":          [],
                "values":          [],
                "source_chunk_ids": ["chunk_002"],
                "raw":             {},
            },
        ]
        index = {"api_endpoints": sigs, "db_models": [], "enums": [],
                 "business_rules": [], "screens": [], "workflows": []}
        cleaned, _ = run_deduplication(index)
        merged_sig = cleaned["api_endpoints"][0]
        # Merged artifact should carry chunk ids from both sources
        self.assertIn("chunk_001", merged_sig["source_chunk_ids"])
        self.assertIn("chunk_002", merged_sig["source_chunk_ids"])


if __name__ == "__main__":
    unittest.main()
