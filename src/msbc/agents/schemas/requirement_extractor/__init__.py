"""
app/modules/requirement_extractor/schemas/__init__.py

Re-exports all schema dicts for convenience.
"""

from src.msbc.agents.schemas.requirement_extractor.segmentation import SEGMENTATION_SCHEMA, CLASSIFICATION_SCHEMA
from src.msbc.agents.schemas.requirement_extractor.frontend import FRONTEND_SCHEMA
from src.msbc.agents.schemas.requirement_extractor.backend import BACKEND_SCHEMA
from src.msbc.agents.schemas.requirement_extractor.combined import COMBINED_SCHEMA
from src.msbc.agents.schemas.requirement_extractor.summary import SUMMARY_SCHEMA
from src.msbc.agents.schemas.requirement_extractor.unified import UNIFIED_SCHEMA
from src.msbc.agents.schemas.requirement_extractor.graph_output import GRAPH_OUTPUT_SCHEMA
from src.msbc.agents.schemas.requirement_extractor.section_classification import (
    SECTION_CLASSIFICATION_SCHEMA,
    CANONICALIZATION_SCHEMA,
)
from src.msbc.agents.schemas.requirement_extractor.module_inventory import (
    MODULE_INVENTORY_SCHEMA,
    MODULE_NORMALIZATION_SCHEMA,
)

__all__ = [
    "SEGMENTATION_SCHEMA",
    "CLASSIFICATION_SCHEMA",
    "FRONTEND_SCHEMA",
    "BACKEND_SCHEMA",
    "COMBINED_SCHEMA",
    "SUMMARY_SCHEMA",
    "UNIFIED_SCHEMA",
    "GRAPH_OUTPUT_SCHEMA",
    "SECTION_CLASSIFICATION_SCHEMA",
    "CANONICALIZATION_SCHEMA",
    "MODULE_INVENTORY_SCHEMA",
    "MODULE_NORMALIZATION_SCHEMA",
]
