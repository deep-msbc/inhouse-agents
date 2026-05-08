"""
module_inventory.py — JSON schema for module_inventory_node LLM output.

The LLM receives a compact document outline (chunk title hints + local headings)
and returns a list of real business module candidates.

One LLM call replaces the old sequential batched section_classifier_node calls.
"""

MODULE_INVENTORY_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["module_candidates"],
    "additionalProperties": False,
    "properties": {
        "module_candidates": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": [
                    "module_key",
                    "display_name",
                    "business_goal",
                    "primary_entities",
                    "evidence_chunk_ids",
                    "child_concepts",
                ],
                "additionalProperties": False,
                "properties": {
                    "module_key": {
                        "type": "string",
                        "description": "snake_case slug of the module name, e.g. 'job_production_tracking'",
                    },
                    "display_name": {
                        "type": "string",
                        "description": "Human-readable module name, e.g. 'Job Production Tracking'",
                    },
                    "business_goal": {
                        "type": "string",
                        "description": "One sentence: what business problem does this module solve?",
                    },
                    "primary_entities": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Main data entities owned by this module (e.g. ['Job', 'Process'])",
                    },
                    "main_actions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Core user actions in this module (e.g. ['Create Job', 'Track Progress'])",
                    },
                    "evidence_chunk_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "chunk_ids that contain the primary content for this module",
                    },
                    "child_concepts": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Sub-screens, forms, grids, workflows, rules that belong INSIDE this module",
                    },
                    "shared_artifacts": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Concepts shared with other modules (e.g. barcodes used by both scanning and tracking)",
                    },
                    "confidence": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "description": "0.0-1.0 confidence that this is a real standalone business module",
                    },
                },
            },
        }
    },
}

# Re-export for backwards-compat with schemas __init__
MODULE_NORMALIZATION_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["canonical_modules"],
    "additionalProperties": False,
    "properties": {
        "canonical_modules": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": [
                    "module_key",
                    "display_name",
                    "business_goal",
                    "primary_entities",
                    "evidence_chunk_ids",
                    "child_concepts",
                ],
                "additionalProperties": False,
                "properties": {
                    "module_key":         {"type": "string"},
                    "display_name":       {"type": "string"},
                    "business_goal":      {"type": "string"},
                    "primary_entities":   {"type": "array", "items": {"type": "string"}},
                    "main_actions":       {"type": "array", "items": {"type": "string"}},
                    "evidence_chunk_ids": {"type": "array", "items": {"type": "string"}},
                    "child_concepts":     {"type": "array", "items": {"type": "string"}},
                    "aliases":            {"type": "array", "items": {"type": "string"}},
                    "confidence":         {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "merge_reason":       {"type": ["string", "null"]},
                },
            },
        }
    },
}
