"""
toolkit_knowledge.py  (Frontend Planner Agent)
───────────────────────────────────────────────
Single source of truth describing the MSBC internal toolkit for the
Frontend Planner LLM.  Update this file whenever packages change; the
prompt builder in planner_prompts.yaml injects it via {toolkit_context}.

Packages covered:
  @msbc/config-ui         — ConfigurableDashboard, ConfigurableForm
  @msbc/react-toolkit     — atomic UI primitives (Button, Input, Dropdown, …)
  @msbc/data-layer        — useApiRequest, createApiSlice, apiClient, createTokenManager
  @msbc/utils             — classname, classnames, cns, isEmpty, useDebounce, …
  @msbc/import-utils      — ImportWizard (CSV/Excel guided import)
  @msbc/config-app-shell  — AppShell, LayoutRoute, ShellRoutes (routing/layout)
"""

from __future__ import annotations

# ─── Package registry ─────────────────────────────────────────────────────────

PACKAGES: dict[str, dict] = {

    # ── config-ui ─────────────────────────────────────────────────────────────
    "config-ui": {
        "import_path": "@msbc/config-ui",
        "description": (
            "High-level configurable UI shells. Use when a full dashboard "
            "or form page is needed. Internally orchestrates react-toolkit "
            "primitives and wires data-layer hooks."
        ),
        "components": {
            "ConfigurableDashboard": {
                "description": (
                    "Renders a data-driven dashboard: table/list, search, "
                    "filters (FilterModal), date pickers, toggle, pagination. "
                    "Accepts a config prop that drives columns, filters, and "
                    "API options. Exposes an imperative handle via forwardRef "
                    "for external refresh / reset. "
                    "Data fetching is handled INTERNALLY via config.api — "
                    "the page component must NOT call a service hook for data "
                    "loading or refresh (refresh is automatic)."
                ),
                "when_to_use": [
                    "Screen is a full-page listing/master grid with server-driven pagination",
                    "Screen needs searchable, filterable, paginated data listing",
                    "Screen needs date-range filtering",
                    "Screen needs column-visibility toggle",
                ],
                "do_not_use_when": [
                    "Grid is embedded inside a form, tab, or popup — use Table instead",
                    "Screen already has a ConfigurableDashboard — do NOT add a separate filter_panel component",
                ],
                "internally_uses": [
                    "Button", "Input", "Dropdown", "Table", "List",
                    "RangeDatePicker", "DatePicker", "ToggleButton",
                    "Pagination", "FilterModal",
                ],
                "data_layer_hooks": ["useApiRequest"],
                "key_config_rules": [
                    "api must be at the TOP LEVEL of DashboardConfig, never inside tableProps",
                    "columns[].name → columnDef.field; columns[].label → columnDef.headerName",
                    "actions[].text is the label key (not 'name')",
                    "api.method must be lowercase: 'get', 'post', 'put', 'delete'",
                    "filters[].type: date-range | date | select | text | int | bool | phone",
                ],
            },
            "ConfigurableForm": {
                "description": (
                    "Schema-driven form engine. Accepts a sections/fields config "
                    "(JSONFormSchema<T>) and renders the correct input component via "
                    "FormComponentRegistry. Uses react-hook-form internally. Supports "
                    "validation rules, conditional visibility (visibleIf), field arrays, "
                    "and custom field overrides."
                ),
                "when_to_use": [
                    "Screen purpose is data entry (create / edit)",
                    "Screen type is 'form' (modal, page, or popup form)",
                    "Form has dynamic field visibility based on other field values",
                    "Form has file upload, map picker, or date fields",
                ],
                "do_not_use_when": [
                    "Only 1–2 inline fields with no form-level validation — use Input/Dropdown directly",
                ],
                "field_types": [
                    "text", "email", "number", "password", "textarea", "tel",
                    "select", "radio", "checkbox", "list",
                    "fileUpload", "map", "date", "date-range",
                ],
                "internally_uses": [
                    "Input", "Dropdown", "RadioGroup", "CheckboxGroup",
                    "List", "FileUpload", "Map", "DatePicker", "RangeDatePicker",
                    "Button",
                ],
                "data_layer_hooks": ["useApiRequest (for dependent dropdowns / submit)"],
                "key_config_rules": [
                    "sections[] each have a title and fields[]",
                    "Each field must have name, label, type, required",
                    "checkbox/radio/select fields MUST have options[] as 'label:value' strings",
                    "validation[] strings → typed rule objects: required, minLength, maxLength, pattern, min, max, custom",
                    "visibleIf enables conditional field visibility",
                ],
            },
        },
    },

    # ── react-toolkit ─────────────────────────────────────────────────────────
    "react-toolkit": {
        "import_path": "@msbc/react-toolkit",
        "description": (
            "Atomic UI primitives. Use directly when config-ui shells are "
            "too heavy or a one-off component is needed outside a full "
            "dashboard / form context."
        ),
        "components": {
            "Button":           "Primary action trigger. Variants: primary, secondary, ghost, text.",
            "Input":            "Text / number / textarea input with label + validation state.",
            "Dropdown":         "Single-select or multi-select dropdown. Supports async API loading via api prop.",
            "Checkbox":         "Single checkbox control. Use when toggling one independent boolean value.",
            "CheckboxGroup":    "Group of checkboxes sharing a name.",
            "RadioGroup":       "Group of radio options.",
            "DatePicker":       "Single date picker. Supports time selection via showTimeSelect.",
            "RangeDatePicker":  "Start–end date range picker.",
            "Table":            "Sortable, configurable column table with built-in pagination. Use for embedded grids (inside form/tab/popup), NOT for the main full-page listing.",
            "List":             "Scrollable item list with optional actions.",
            "FileUpload":       "Drag-and-drop file upload control (FilePond-based). Use for type=upload_zone.",
            "Map":              "Location picker / map embed.",
            "Modal":            "Overlay dialog with header / body / footer slots. Sizes: sm, md, lg, full. Use as outer shell for modal form screens.",
            "FilterModal":      "Pre-built filter dialog. Already bundled inside ConfigurableDashboard — do NOT add separately when the screen uses ConfigurableDashboard.",
            "FormFieldWrapper": "Wraps any custom input with label, helpText, error, isRequired, isDisabled. Use for custom fields outside ConfigurableForm.",
            "Badge":            "Status / label badge with auto-contrast text. Sizes: sm, md, lg. Use for KPI tiles, scan feedback states, and feedback_area banners.",
            "Pagination":       "Page-number navigator (also embedded inside Table).",
            "TabNav":           "Horizontal tab navigation with lazy/keepAlive content rendering. Use for type=tabs.",
            "ToggleButton":     "On/off toggle (e.g. show/hide columns). Built into ConfigurableDashboard.",
            "FilterChip":       "Removable filter tag chip shown above a grid.",
            "MultipleItem":     "Multi-value tag input.",
        },
    },

    # ── data-layer ────────────────────────────────────────────────────────────
    "data-layer": {
        "import_path": "@msbc/data-layer",
        "description": (
            "API plumbing: axios instance, token management, RTK Query slice "
            "factory, and a generic useApiRequest hook. Use whenever a module "
            "fetches or mutates server data."
        ),
        "exports": {
            "useApiRequest": (
                "Primary hook for GET/POST/PUT/DELETE. Accepts UseApiOptions "
                "(url, method, params, body, enabled). Returns "
                "{ data, loading, error, refetch }."
            ),
            "createApiSlice": (
                "RTK Query slice factory for modules that need Redux-cached "
                "endpoints. Prefer for shared / frequently-invalidated data "
                "accessed by more than one component."
            ),
            "apiClient":          "Typed axios wrapper for one-off imperative GET/POST/PUT/PATCH/DELETE calls.",
            "createTokenManager": "Factory that returns token get/set/clear/refresh methods. Configurable storage, keys, and refresh endpoint.",
        },
        "when_to_use": [
            "Any module that calls a REST endpoint",
            "Forms that need server-side validation or submit",
            "Dashboards with server-driven pagination / search",
            "Modules that share cached server state across components",
        ],
        "data_hook_selection_guide": [
            "Single-component GET/POST/PUT/DELETE with no Redux caching → useApiRequest",
            "Module-wide shared data invalidated across multiple components → createApiSlice",
            "Display-only component, no server calls → data_hook = '' (empty string)",
            "ConfigurableDashboard fetches data internally — do NOT add useApiRequest at page level for data loading",
        ],
    },

    # ── utils ─────────────────────────────────────────────────────────────────
    "utils": {
        "import_path": "@msbc/utils",
        "description": "Shared utility functions used across all packages.",
        "exports": {
            "classname":                "BEM class-name builder (withNaming from @bem-react/classname). Creates block__element--modifier strings.",
            "classnames":               "The 'classnames' library. Build conditional class lists.",
            "cns":                      "Alias for classnames. Shorthand for conditional class composition.",
            "isEmpty":                  "Returns true for null / undefined / empty-string / empty-array / empty-object.",
            "useDebounce":              "Returns a debounced copy of a value. Pass value and delay ms.",
            "useDebouncedCallback":     "Returns a debounced version of a callback function.",
            "getMinContrastForeground": "Given a background hex color, returns a foreground color meeting WCAG AA (4.5:1).",
            "MIN_CONTRAST_RATIO":       "WCAG AA minimum contrast constant (4.5).",
        },
    },

    # ── import-utils ──────────────────────────────────────────────────────────
    "import-utils": {
        "import_path": "@msbc/import-utils",
        "description": (
            "Multi-step CSV / Excel import wizard. Use when a module needs "
            "a guided file-upload → column-mapping → submit flow."
        ),
        "components": {
            "ImportWizard": {
                "description": (
                    "Config-driven three-step import wizard: module selection, "
                    "file upload, and field mapping (FieldMapper). "
                    "Drives all steps via a single ImportWizardConfig object "
                    "that specifies API endpoints, form configs, response mappers, "
                    "and labels. Emits onSuccess / onError callbacks."
                ),
                "when_to_use": [
                    "Module needs to import data from a CSV or Excel file",
                    "Module needs a guided column-to-field mapping step",
                    "Module needs server-side header extraction before mapping",
                ],
                "internally_uses": ["FieldMapper", "ConfigurableForm", "useApiRequest"],
                "data_layer_hooks": ["useApiRequest"],
            },
        },
    },

    # ── config-app-shell ──────────────────────────────────────────────────────
    "config-app-shell": {
        "import_path": "@msbc/config-app-shell",
        "description": (
            "Application shell primitives for React Router v6 micro-frontends. "
            "Use when wiring top-level routing, layout (header + sidebar), "
            "and declarative route-to-component mapping."
        ),
        "components": {
            "AppShell": {
                "description": (
                    "Full application shell. Owns a BrowserRouter, renders AppLayout "
                    "(header + sidebar), and maps a routes[] config to React components "
                    "via a components record. Each route can carry an optional configPath "
                    "string passed as a prop to the rendered component."
                ),
                "when_to_use": [
                    "Top-level entry point that owns the Router and layout",
                    "Route list is data-driven (JSON config)",
                ],
            },
            "LayoutRoute": {
                "description": (
                    "Header + sidebar layout with a React Router <Outlet />. "
                    "Use inside an existing Router when AppShell's BrowserRouter "
                    "is not wanted (e.g. inside a micro-frontend that shares a Router)."
                ),
            },
            "ShellRoutes": {
                "description": (
                    "Declarative <Routes> renderer. Maps a routes[] config array "
                    "to components without owning a Router or layout. "
                    "Use when you already have a Router and layout and only need "
                    "the route → component wiring."
                ),
            },
        },
    },
}


# ─── Component type → toolkit mapping ────────────────────────────────────────
# Deterministic lookup: component type → exact toolkit_mapping string for the LLM.

COMPONENT_TYPE_MAPPING: dict[str, str] = {
    "toolbar":        "Button",                    # one Button per action; no Toolbar primitive
    "grid":           "ConfigurableDashboard",     # full-page listing screen
    "grid_embedded":  "Table",                     # grid inside form / tab / popup
    "form":           "ConfigurableForm",          # modal or full-page data-entry form
    "form_simple":    "Input, Dropdown",           # 1-2 inline fields, no full form engine
    "filter_panel":   "FilterModal",               # dialog-style (non-dashboard screens only)
    "filter_inline":  "Dropdown, RangeDatePicker", # inline chip-style filters
    "tabs":           "TabNav",
    "info_panel":     "Input",                     # readonly=true display fields
    "scan_panel":     "Input",                     # single barcode/RFID field + Badge feedback
    "kpi":            "Badge",                     # count/status summary tiles, no mutation
    "upload_zone":    "FileUpload",
    "import_wizard":  "ImportWizard",              # CSV/Excel guided import flow
    "stepper":        "Button, Modal",             # no Stepper primitive — model with step index state
    "feedback_area":  "Badge",                     # no Toast/Snackbar — Badge or styled div
    "barcode_panel":  "Input, Button",             # display barcode + print/download
}


# ─── Strict field / filter type tables ───────────────────────────────────────

ALLOWED_FIELD_TYPES: list[str] = [
    "text", "email", "number", "password", "textarea", "tel",
    "select", "radio", "checkbox", "list",
    "fileUpload", "map", "date", "date-range",
]

FIELD_TYPE_ALIASES: dict[str, str] = {
    # forbidden alias  → correct type
    "dropdown":     "select",
    "toggle":       "checkbox",
    "phone":        "tel",
    "multi_select": "select",
    "integer":      "number",
    "date_range":   "date-range",
    "bool":         "checkbox",
    "boolean":      "checkbox",
}

ALLOWED_FILTER_TYPES: list[str] = [
    "text", "select", "date", "date-range", "int", "bool", "phone",
]

FILTER_TYPE_ALIASES: dict[str, str] = {
    "dropdown":     "select",
    "date_range":   "date-range",
    "multi_select": "select",
    "boolean":      "bool",
    "integer":      "int",
    "tel":          "phone",
}


# ─── File-structure path conventions ─────────────────────────────────────────

FILE_STRUCTURE_RULES: dict[str, str] = {
    "page":      "src/modules/<ModuleName>/pages/<ScreenName>Page.tsx",
    "config":    "src/modules/<ModuleName>/config/<ScreenName>.config.ts",
    "form":      "src/modules/<ModuleName>/forms/<FormName>.tsx",
    "component": "src/modules/<ModuleName>/components/<ComponentName>.tsx",
    "service":   "src/modules/<ModuleName>/services/<ModuleName>.service.ts",
    "hook":      "src/modules/<ModuleName>/hooks/use<ModuleName>.ts",
    "types":     "src/modules/<ModuleName>/<ModuleName>.types.ts",
}

MANDATORY_FILES_PER_MODULE: list[str] = [
    "types   — ALWAYS one per module (TypeScript interfaces for all data shapes).",
    "config  — ALWAYS one per screen using ConfigurableDashboard or ConfigurableForm.",
    "service — ALWAYS one per module (all API hooks wrapped from useApiRequest).",
    "page    — one per full-page screen (opens_as=page).",
    "form    — one per modal/popup form screen.",
]


# ─── Prompt-ready context builder ─────────────────────────────────────────────

def build_toolkit_context() -> str:
    """
    Returns a compact, token-efficient description of the MSBC toolkit for
    injection into planner prompts.  Includes:
      - Per-package component/export listings with guidance
      - Component type → toolkit_mapping lookup table
      - Strict field/filter type tables with forbidden aliases
      - File structure conventions
      - Decision guide
    """
    lines: list[str] = [
        "═══════════════════════════════════════════════════",
        "MSBC INTERNAL TOOLKIT  (use ONLY these packages)",
        "═══════════════════════════════════════════════════",
        "",
    ]

    for pkg_key, pkg in PACKAGES.items():
        lines.append(f"[{pkg['import_path']}]")
        lines.append(f"  {pkg['description']}")
        lines.append("")

        if "components" in pkg:
            for comp, meta in pkg["components"].items():
                if isinstance(meta, dict):
                    lines.append(f"  • {comp}")
                    lines.append(f"    {meta['description']}")
                    if "when_to_use" in meta:
                        lines.append(f"    USE WHEN: {' | '.join(meta['when_to_use'])}")
                    if "do_not_use_when" in meta:
                        lines.append(f"    DO NOT USE: {' | '.join(meta['do_not_use_when'])}")
                    if "data_layer_hooks" in meta:
                        lines.append(f"    data_hook: {', '.join(meta['data_layer_hooks'])}")
                    if "field_types" in meta:
                        lines.append(f"    field types: {' | '.join(meta['field_types'])}")
                    if "key_config_rules" in meta:
                        lines.append(f"    config rules: {' | '.join(meta['key_config_rules'])}")
                else:
                    lines.append(f"  • {comp}: {meta}")

        if "exports" in pkg:
            for export, desc in pkg["exports"].items():
                lines.append(f"  • {export}: {desc}")

        if "data_hook_selection_guide" in pkg:
            lines.append("  Data-hook selection:")
            for rule in pkg["data_hook_selection_guide"]:
                lines.append(f"    – {rule}")

        if "when_to_use" in pkg and "components" not in pkg:
            lines.append(f"  USE WHEN: {' | '.join(pkg['when_to_use'])}")

        lines.append("")

    # ── Component type → toolkit_mapping table ─────────────────────────────
    lines += [
        "─────────────────────────────────────────────────────",
        "COMPONENT TYPE → TOOLKIT MAPPING  (use exactly these)",
        "─────────────────────────────────────────────────────",
    ]
    for ctype, mapping in COMPONENT_TYPE_MAPPING.items():
        lines.append(f"  {ctype:<18} → {mapping}")

    # ── Field type tables ─────────────────────────────────────────────────
    lines += [
        "",
        "─────────────────────────────────────────────────────",
        "FIELD TYPE RULES",
        "─────────────────────────────────────────────────────",
        f"  Allowed fields[].type : {' | '.join(ALLOWED_FIELD_TYPES)}",
        "  Forbidden aliases (translate before output):",
    ]
    for alias, correct in FIELD_TYPE_ALIASES.items():
        lines.append(f"    {alias} → {correct}")

    lines += [
        "",
        f"  Allowed filters[].type: {' | '.join(ALLOWED_FILTER_TYPES)}",
        "  Forbidden filter aliases:",
    ]
    for alias, correct in FILTER_TYPE_ALIASES.items():
        lines.append(f"    {alias} → {correct}")

    # ── Mandatory files ───────────────────────────────────────────────────
    lines += [
        "",
        "─────────────────────────────────────────────────────",
        "MANDATORY FILES PER MODULE",
        "─────────────────────────────────────────────────────",
    ]
    for rule in MANDATORY_FILES_PER_MODULE:
        lines.append(f"  • {rule}")

    # ── Decision guide ────────────────────────────────────────────────────
    lines += [
        "",
        "─────────────────────────────────────────────────────",
        "DECISION GUIDE",
        "─────────────────────────────────────────────────────",
        "  Full listing page (opens_as=page)       → ConfigurableDashboard + useApiRequest (internal to config)",
        "  Create / edit form (modal or page)      → ConfigurableForm + useApiRequest",
        "  Embedded sub-grid (tab/popup/form)      → Table + useApiRequest",
        "  CSV/Excel guided import flow            → ImportWizard (@msbc/import-utils)",
        "  App-level routing + layout shell        → AppShell / LayoutRoute / ShellRoutes (@msbc/config-app-shell)",
        "  Scan / barcode entry                    → Input + Badge (feedback states)",
        "  Status summary tiles (KPI)              → Badge (display-only, no data hook)",
        "  Shared/frequently-invalidated data      → createApiSlice",
        "  Any other server data                   → useApiRequest",
        "  Utility (debounce, classnames, …)       → @msbc/utils",
        "  ConfigurableDashboard bundles FilterModal + Pagination — do NOT add them separately on the same screen.",
    ]

    return "\n".join(lines)


# ─── Quick preview ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(build_toolkit_context())
