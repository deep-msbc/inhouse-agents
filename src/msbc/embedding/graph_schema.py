"""
KUZU graph schema DDL constants for the toolkit knowledge graph.

All statements use ``IF NOT EXISTS`` so they are idempotent — safe to run
on every startup or ``build_graph`` call.

Node tables
-----------
Package       — @msbc/* npm package (e.g. @msbc/config-ui)
Component     — exported React component or hook  (semantic registry)
TypeDef       — TypeScript interface / type used by a component
Feature       — named capability flag  (e.g. has_search, has_filters)
FieldType     — form field type  (e.g. fileUpload, select)
Example       — one correct_code_examples/{group}/{id}/ folder
ExampleFile   — one source file within an Example folder

Code-graph node tables (built from scanning the actual monorepo source)
------------------------------------------------------------------------
SourceFile    — one .ts / .tsx file inside a package
ExportedSymbol— a named symbol exported by a SourceFile

Relationship tables (semantic graph)
-------------------------------------
BelongsTo           Component → Package
InternallyUses      Component → Component  (orchestration / composition)
UsesType            Component → TypeDef    (config prop or generic param)
UsesHook            Component → Component  (data-layer hook dependency)
ExhibitsFeature     Component → Feature    (also Example → Feature)
SupportsFieldType   Component → FieldType
DemonstratesComponent Example → Component
ExhibitsFieldType   Example → FieldType
HasFile             Example → ExampleFile

Relationship tables (code graph)
----------------------------------
FileBelongsTo        SourceFile → Package
ImportsFrom          SourceFile → SourceFile   (intra-package resolved imports)
ImportsPackage       SourceFile → Package      (cross-package / external imports)
ExportsSymbol        SourceFile → ExportedSymbol
ReExportsFrom        SourceFile → SourceFile   (export * from '...')
SymbolLinkedToComponent ExportedSymbol → Component  (code ↔ semantic link)
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
# Code-graph node table DDL  (built from scanning the real monorepo)
# ---------------------------------------------------------------------------

# Primary key: "{package_name}::{rel_path}"
# e.g. "@msbc/config-ui::src/components/ConfigurableDashboard/ConfigurableDashboard.tsx"
CREATE_SOURCEFILE = """
CREATE NODE TABLE IF NOT EXISTS SourceFile(
    id           STRING,
    file_name    STRING,
    rel_path     STRING,
    package_name STRING,
    file_type    STRING,
    PRIMARY KEY (id)
)
"""

# Primary key: "{package_name}::{symbol_name}"
# e.g. "@msbc/config-ui::ConfigurableDashboard"
CREATE_EXPORTEDSYMBOL = """
CREATE NODE TABLE IF NOT EXISTS ExportedSymbol(
    id           STRING,
    name         STRING,
    symbol_type  STRING,
    package_name STRING,
    PRIMARY KEY (id)
)
"""

# ---------------------------------------------------------------------------
# Code-graph relationship table DDL
# ---------------------------------------------------------------------------

CREATE_FILE_BELONGS_TO = """
CREATE REL TABLE IF NOT EXISTS FileBelongsTo(
    FROM SourceFile TO Package
)
"""

# Import of another file within the same (or different) package — resolved.
# import_specifiers: list of named symbols imported (e.g. ['Button', 'ButtonProps'])
CREATE_IMPORTS_FROM = """
CREATE REL TABLE IF NOT EXISTS ImportsFrom(
    FROM SourceFile TO SourceFile,
    import_specifiers STRING[]
)
"""

# Import from an @msbc/* package (cross-package or external npm package).
CREATE_IMPORTS_PACKAGE = """
CREATE REL TABLE IF NOT EXISTS ImportsPackage(
    FROM SourceFile TO Package,
    import_specifiers STRING[]
)
"""

CREATE_EXPORTS_SYMBOL = """
CREATE REL TABLE IF NOT EXISTS ExportsSymbol(
    FROM SourceFile TO ExportedSymbol
)
"""

# export * from './path'  →  source re-exports everything from target
CREATE_REEXPORTS_FROM = """
CREATE REL TABLE IF NOT EXISTS ReExportsFrom(
    FROM SourceFile TO SourceFile
)
"""

# Bridge between the code graph and the semantic component registry.
CREATE_SYMBOL_LINKED_TO_COMPONENT = """
CREATE REL TABLE IF NOT EXISTS SymbolLinkedToComponent(
    FROM ExportedSymbol TO Component
)
"""

# ---------------------------------------------------------------------------
# Ordered list of all DDL statements (node tables first, then rel tables)
# ---------------------------------------------------------------------------

ALL_DDL: list[str] = [
    # Semantic node tables
    CREATE_PACKAGE,
    CREATE_COMPONENT,
    CREATE_TYPEDEF,
    CREATE_FEATURE,
    CREATE_FIELDTYPE,
    CREATE_EXAMPLE,
    CREATE_EXAMPLEFILE,
    # Code-graph node tables
    CREATE_SOURCEFILE,
    CREATE_EXPORTEDSYMBOL,
    # Semantic relationship tables
    CREATE_BELONGS_TO,
    CREATE_INTERNALLY_USES,
    CREATE_USES_TYPE,
    CREATE_USES_HOOK,
    CREATE_EXHIBITS_FEATURE,
    CREATE_SUPPORTS_FIELD_TYPE,
    CREATE_DEMONSTRATES_COMPONENT,
    CREATE_EXHIBITS_FIELD_TYPE,
    CREATE_HAS_FILE,
    # Code-graph relationship tables
    CREATE_FILE_BELONGS_TO,
    CREATE_IMPORTS_FROM,
    CREATE_IMPORTS_PACKAGE,
    CREATE_EXPORTS_SYMBOL,
    CREATE_REEXPORTS_FROM,
    CREATE_SYMBOL_LINKED_TO_COMPONENT,
]

# ---------------------------------------------------------------------------
# Drop order (reverse of creation; rels must be dropped before their node tables)
# ---------------------------------------------------------------------------

DROP_ORDER: list[str] = [
    # Code-graph relationship tables first (they reference both graphs)
    "SymbolLinkedToComponent",
    "ReExportsFrom",
    "ExportsSymbol",
    "ImportsPackage",
    "ImportsFrom",
    "FileBelongsTo",
    # Semantic relationship tables
    "HasFile",
    "ExhibitsFieldType",
    "DemonstratesComponent",
    "SupportsFieldType",
    "ExhibitsFeature",
    "UsesHook",
    "UsesType",
    "InternallyUses",
    "BelongsTo",
    # Code-graph node tables
    "ExportedSymbol",
    "SourceFile",
    # Semantic node tables
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
    "fileUpload", "map", "date", "date-range", "custom",
]
