"""
KUZU graph schema DDL constants for the toolkit knowledge graph.

All statements use ``IF NOT EXISTS`` so they are idempotent — safe to run
on every startup or ``build_graph`` call.

Node tables
-----------
Package       — @msbc/* npm package (e.g. @msbc/config-ui)
Component     — exported React component or hook
TypeDef       — TypeScript interface / type used by a component
Feature       — named capability flag  (e.g. has_search, has_filters)
FieldType     — form field type  (e.g. fileUpload, select)
Example       — one correct_code_examples/{group}/{id}/ folder
ExampleFile   — one source file within an Example folder

Relationship tables
-------------------
BelongsTo           Component → Package
InternallyUses      Component → Component  (orchestration / composition)
UsesType            Component → TypeDef    (config prop or generic param)
UsesHook            Component → Component  (data-layer hook dependency)
ExhibitsFeature     Component → Feature    (also Example → Feature)
SupportsFieldType   Component → FieldType
DemonstratesComponent Example → Component
ExhibitsFieldType   Example → FieldType
HasFile             Example → ExampleFile
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Node table DDL
# ---------------------------------------------------------------------------

# Primary key for Package is its npm import path, e.g. "@msbc/config-ui".
CREATE_PACKAGE = """
CREATE NODE TABLE IF NOT EXISTS Package(
    name        STRING,
    import_path STRING,
    description STRING,
    PRIMARY KEY (name)
)
"""

# Primary key is a scoped identifier: "{import_path}::{component_name}",
# e.g. "@msbc/config-ui::ConfigurableDashboard".
# when_to_use / do_not_use_when stored as STRING[] (kuzu list type).
CREATE_COMPONENT = """
CREATE NODE TABLE IF NOT EXISTS Component(
    id               STRING,
    name             STRING,
    component_type   STRING,
    description      STRING,
    when_to_use      STRING[],
    do_not_use_when  STRING[],
    PRIMARY KEY (id)
)
"""

# Primary key: "{import_path}::{type_name}", e.g. "@msbc/config-ui::DashboardConfig".
CREATE_TYPEDEF = """
CREATE NODE TABLE IF NOT EXISTS TypeDef(
    id              STRING,
    name            STRING,
    description     STRING,
    required_fields STRING[],
    PRIMARY KEY (id)
)
"""

# Primary key: canonical feature name, e.g. "has_search".
CREATE_FEATURE = """
CREATE NODE TABLE IF NOT EXISTS Feature(
    name  STRING,
    label STRING,
    PRIMARY KEY (name)
)
"""

# Primary key: canonical field type name, e.g. "fileUpload".
CREATE_FIELDTYPE = """
CREATE NODE TABLE IF NOT EXISTS FieldType(
    name STRING,
    PRIMARY KEY (name)
)
"""

# Primary key: example_id (folder name), e.g. "Dashboard03".
CREATE_EXAMPLE = """
CREATE NODE TABLE IF NOT EXISTS Example(
    example_id      STRING,
    example_group   STRING,
    pattern         STRING,
    complexity      STRING,
    use_case        STRING,
    qdrant_chunk_ids STRING[],
    PRIMARY KEY (example_id)
)
"""

# Primary key: "{example_id}::{file_name}", e.g. "Dashboard03::dashboard3config.ts".
CREATE_EXAMPLEFILE = """
CREATE NODE TABLE IF NOT EXISTS ExampleFile(
    id              STRING,
    file_name       STRING,
    file_role       STRING,
    file_path       STRING,
    qdrant_chunk_id STRING,
    PRIMARY KEY (id)
)
"""

# ---------------------------------------------------------------------------
# Relationship table DDL
# ---------------------------------------------------------------------------

CREATE_BELONGS_TO = """
CREATE REL TABLE IF NOT EXISTS BelongsTo(
    FROM Component TO Package
)
"""

CREATE_INTERNALLY_USES = """
CREATE REL TABLE IF NOT EXISTS InternallyUses(
    FROM Component TO Component,
    note STRING
)
"""

CREATE_USES_TYPE = """
CREATE REL TABLE IF NOT EXISTS UsesType(
    FROM Component TO TypeDef,
    role STRING
)
"""

CREATE_USES_HOOK = """
CREATE REL TABLE IF NOT EXISTS UsesHook(
    FROM Component TO Component
)
"""

# Shared by both Component→Feature and Example→Feature.
# KUZU supports multiple FROM→TO pairs in one REL TABLE definition.
CREATE_EXHIBITS_FEATURE = """
CREATE REL TABLE IF NOT EXISTS ExhibitsFeature(
    FROM Component TO Feature,
    FROM Example TO Feature
)
"""

CREATE_SUPPORTS_FIELD_TYPE = """
CREATE REL TABLE IF NOT EXISTS SupportsFieldType(
    FROM Component TO FieldType
)
"""

CREATE_DEMONSTRATES_COMPONENT = """
CREATE REL TABLE IF NOT EXISTS DemonstratesComponent(
    FROM Example TO Component
)
"""

CREATE_EXHIBITS_FIELD_TYPE = """
CREATE REL TABLE IF NOT EXISTS ExhibitsFieldType(
    FROM Example TO FieldType
)
"""

CREATE_HAS_FILE = """
CREATE REL TABLE IF NOT EXISTS HasFile(
    FROM Example TO ExampleFile
)
"""

# ---------------------------------------------------------------------------
# Ordered list of all DDL statements (node tables first, then rel tables)
# ---------------------------------------------------------------------------

ALL_DDL: list[str] = [
    # Node tables
    CREATE_PACKAGE,
    CREATE_COMPONENT,
    CREATE_TYPEDEF,
    CREATE_FEATURE,
    CREATE_FIELDTYPE,
    CREATE_EXAMPLE,
    CREATE_EXAMPLEFILE,
    # Relationship tables
    CREATE_BELONGS_TO,
    CREATE_INTERNALLY_USES,
    CREATE_USES_TYPE,
    CREATE_USES_HOOK,
    CREATE_EXHIBITS_FEATURE,
    CREATE_SUPPORTS_FIELD_TYPE,
    CREATE_DEMONSTRATES_COMPONENT,
    CREATE_EXHIBITS_FIELD_TYPE,
    CREATE_HAS_FILE,
]

# ---------------------------------------------------------------------------
# Drop order (reverse of creation; rels must be dropped before their node tables)
# ---------------------------------------------------------------------------

DROP_ORDER: list[str] = [
    # Relationship tables first
    "HasFile",
    "ExhibitsFieldType",
    "DemonstratesComponent",
    "SupportsFieldType",
    "ExhibitsFeature",
    "UsesHook",
    "UsesType",
    "InternallyUses",
    "BelongsTo",
    # Node tables
    "ExampleFile",
    "Example",
    "FieldType",
    "Feature",
    "TypeDef",
    "Component",
    "Package",
]

# ---------------------------------------------------------------------------
# Known feature flags (canonical names used as Feature node PKs)
# ---------------------------------------------------------------------------

ALL_FEATURES: list[tuple[str, str]] = [
    # (name, label)
    ("has_search",                "Search"),
    ("has_filters",               "Filters"),
    ("has_actions",               "Bulk actions"),
    ("has_list_view",             "List/card view toggle"),
    ("has_mode_switch",           "Table/grid mode switch"),
    ("has_pagination",            "Pagination"),
    ("has_advance_filters",       "Advanced filter modal"),
    ("has_api_integration",       "API integration"),
    ("has_row_selection",         "Row selection"),
    ("has_sections",              "Form sections"),
    ("has_nested_groups",         "Nested field groups"),
    ("has_custom_validators",     "Custom validators"),
    ("has_custom_component",      "Custom rendered field"),
    ("has_conditional_visibility","Conditional visibility (visibleIf)"),
    ("has_conditional_validation","Conditional required (requiredIf)"),
    ("has_dependent_fields",      "Dependent fields"),
    ("has_file_upload",           "File upload"),
]

# ---------------------------------------------------------------------------
# Known form field types (canonical names used as FieldType node PKs)
# ---------------------------------------------------------------------------

ALL_FIELD_TYPES: list[str] = [
    "text", "email", "number", "password", "textarea", "tel",
    "select", "radio", "checkbox", "list",
    "fileUpload", "map", "date", "date-range",
]
