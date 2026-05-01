"""
toolkit_knowledge.py  (Frontend Planner Agent)
───────────────────────────────────────────────
Single source of truth describing the MSBC internal toolkit for the
Frontend Planner LLM.  Generated from actual TypeScript source files in
the ReactToolKits monorepo.  Update this file whenever packages change;
the prompt builder in planner_prompts.yaml injects it via {toolkit_context}.

Packages covered:
  @msbc/config-ui         — ConfigurableDashboard, ConfigurableForm
  @msbc/react-toolkit     — atomic UI primitives (Button, Input, Dropdown, …)
  @msbc/data-layer        — useApiRequest, createApiSlice, apiClient, tokenManager
  @msbc/utils             — classname, classnames, cns, isEmpty, useDebounce, …
  @msbc/import-utils      — ImportWizard, FieldMapper
  @msbc/config-app-shell  — AppShell, LayoutRoute, ShellRoutes
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
                    "Renders a data-driven dashboard: table/list view, search bar, "
                    "inline filters (Input/Dropdown/DatePicker/RangeDatePicker), "
                    "advanced FilterModal, ToggleButton mode switch, actions[], and "
                    "server-driven pagination. Accepts a single `config: DashboardConfig` "
                    "prop. Data fetching is handled INTERNALLY — the page component must "
                    "NOT add a useApiRequest for data loading (it is automatic). "
                    "Supports forwardRef imperative handle for external refresh/reset."
                ),
                "when_to_use": [
                    "Screen is a full-page listing/master grid with server-driven pagination",
                    "Screen needs searchable, filterable, paginated data listing",
                    "Screen needs date-range filtering or advanced filter modal",
                    "Screen needs table/list view toggle",
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
                "data_layer_hooks": ["useApiRequest (internal — do NOT add at page level for data loading)"],
                "key_props": {
                    "config": "DashboardConfig<TRow, TFilter> — entire dashboard behaviour",
                    "onSearch": "(value: string) => void — triggered on search-bar input",
                    "onFilterChange": "<K extends keyof TFilter>(key: K, value: TFilter[K]) => void",
                    "className": "string?",
                },
                "DashboardConfig_fields": {
                    "title": "React.ReactNode — dashboard heading",
                    "api": "UseApiOptions — MUST be at top level, never inside tableProps",
                    "apiResponseMapper": "(data: any) => { data: any[]; currentPage?; totalRecords?; totalPage? }",
                    "tableProps": "Omit<TableProps<TRow>, 'api'|'rowData'> — column defs go here",
                    "listProps": "Omit<ListProps, 'api'>",
                    "viewMode": "'table' | 'list' (default: 'table')",
                    "enableModeSwitch": "boolean — shows table/list toggle button",
                    "modeSwitchProps": "ToggleButtonProps",
                    "hasSearch": "boolean",
                    "searchBarProps": "Omit<InputProps, 'value'|'onChange'>",
                    "filters": "FiltersType<TFilter>[] — each has name + type (text|select|date|date-range)",
                    "actions": "DashboardAction[] — each extends ButtonProps with api?, onClick?(rows), confirmation?",
                    "hiddenCreateButton": "boolean",
                    "createButtonProps": "ButtonProps",
                    "customCreateButton": "React.ReactNode",
                    "paginationParams": "{ pageIndex?: string; pageLimit?: string }",
                    "autoAdjustColumns": "boolean",
                    "advanceFilterProps": "AdvanceFilterProps — controls FilterModal integration",
                },
                "key_config_rules": [
                    "api must be at the TOP LEVEL of DashboardConfig, never inside tableProps",
                    "columns[].field → ag-Grid columnDef field; columns[].headerName → column label",
                    "actions[].text is the button label (not 'name')",
                    "api.method must be lowercase: 'get', 'post', 'put', 'delete'",
                    "filters[].type: 'text' | 'select' | 'date' | 'date-range' (no 'int'/'bool' in inline filters)",
                    "DashboardAction.onClick receives the selected row array as argument",
                ],
            },
            "ConfigurableForm": {
                "description": (
                    "Schema-driven form engine. Accepts a `config: JSONFormSchema` "
                    "and renders the correct input component via FormComponentRegistry. "
                    "Uses react-hook-form internally. Supports ValidationRule, conditional "
                    "visibility (visibleIf with AND/OR/custom), field arrays (repeatable "
                    "sections), DependsConfig for dependent dropdowns, and custom field "
                    "overrides via component or render props."
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
                "key_props": {
                    "config": "JSONFormSchema — drives form layout, sections, and fields",
                    "defaultValues": "Record<string, unknown>? — pre-filled form values",
                    "onSubmit": "(data: Record<string, unknown>) => void | Promise<void>",
                    "className": "string?",
                    "formClassName": "string?",
                    "error": "string? — top-level error message",
                    "primaryButtonProps": "ButtonProps?",
                    "secondaryButtonProps": "ButtonProps?",
                    "hasSecondaryButton": "boolean?",
                    "hasFooterButtons": "boolean?",
                    "footer": "() => React.ReactNode?",
                    "onDirtyChange": "(isDirty: boolean) => void?",
                    "customValidators": "Record<string, (value, fieldValues) => boolean|string|Promise<boolean|string>>?",
                    "actionButtonPosition": "'top' | 'bottom' | 'both'?",
                    "renderSection": "(SectionRenderProps) => React.ReactNode?",
                    "renderGroup": "(GroupRenderProps) => React.ReactNode?",
                    "renderRepeatableSection": "(RepeatableRenderProps) => React.ReactNode?",
                },
                "JSONFormSchema_fields": {
                    "title": "React.ReactNode?",
                    "description": "React.ReactNode?",
                    "layout": "FormLayout? — { columns?: number }",
                    "sections": "FormContent[]? — FormSection | FormSectionGroup objects",
                    "fields": "FormFieldSchema[]? — flat field list (alternative to sections)",
                },
                "FormSection_fields": {
                    "title": "React.ReactNode?",
                    "description": "React.ReactNode?",
                    "fields": "FormFieldSchema[] — field definitions",
                    "layout": "FormLayout? — { columns: number }",
                    "className": "string?",
                    "colSpan": "number?",
                    "rowSpan": "number?",
                    "repeatable": "boolean? — renders as field array (add/remove rows)",
                    "name": "string? — required when repeatable=true",
                    "minItems": "number?",
                    "maxItems": "number?",
                    "addLabel": "React.ReactNode?",
                    "removeLabel": "React.ReactNode?",
                },
                "FormSectionGroup_fields": {
                    "type": "'group' (required literal)",
                    "sections": "FormSection[]",
                    "variant": "'card' | 'accordion' | 'tabs' | 'plain'?",
                    "title": "React.ReactNode?",
                    "visibleIf": "VisibilityRule? — group-level conditional visibility",
                    "layout": "FormLayout?",
                    "className": "string?",
                },
                "BaseField_props": {
                    "name": "string (required) — field key in form values",
                    "default": "unknown? — initial value",
                    "colSpan": "number?",
                    "rowSpan": "number?",
                    "visibleIf": "VisibilityRule? — conditional visibility",
                    "validation": "ValidationRule?",
                    "depends": "DependsConfig? — dependent dropdown wiring",
                },
                "ValidationRule_props": {
                    "required": "boolean | { message: string }",
                    "requiredIf": "{ field, operator?('equals'|'notEquals'|'exists'|'notEmpty'), value?, message? }",
                    "minLength": "number | { value, message }",
                    "maxLength": "number | { value, message }",
                    "min": "number | { value, message }",
                    "max": "number | { value, message }",
                    "pattern": "string | { value, message }",
                    "custom": "{ fn: string; message: string }",
                },
                "VisibilityRule_operators": [
                    "equals", "notEquals", "exists", "in", "notIn", "custom",
                ],
                "DependsConfig_props": {
                    "fieldName": "string — parent field whose value triggers this field (NOT this field's own name)",
                    "api": "{ mapParamTo?: string; appendToUrl?: boolean }?",
                    "confirm": "{ message: string }?",
                    "when": "(value, allValues) => boolean?",
                    "populate": "{ from, to, transform?, onlyIfEmpty? } | array of same",
                },
                "field_types": [
                    "text", "email", "number", "password", "textarea", "tel",
                    "select", "radio", "checkbox", "list",
                    "fileUpload", "map", "date", "date-range", "custom",
                ],
                "internally_uses": [
                    "Input", "Dropdown", "RadioGroup", "CheckboxGroup",
                    "List", "FileUpload", "Map", "DatePicker", "RangeDatePicker",
                    "Button",
                ],
                "data_layer_hooks": ["useApiRequest (for dependent dropdowns and form submit)"],
                "key_config_rules": [
                    "sections[] each have a title and fields[]",
                    "Each field must have name and type",
                    "select/checkbox/radio fields must have options[] or api prop",
                    "ValidationRule is an object — not an array of strings",
                    "visibleIf enables conditional field visibility (operators: equals|notEquals|exists|in|notIn|custom)",
                    "FormSectionGroup type: 'group' is a required literal string",
                    "VisibilityRule AND/OR operators are uppercase",
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
            "Button": {
                "description": "Primary action trigger. Extends React.ButtonHTMLAttributes.",
                "key_props": (
                    "variant('ghost'|'primary'|'secondary'|'text'), text, "
                    "size('small'|'medium'|'large'), icon(ReactNode), "
                    "iconPosition('left'|'right'), disabled, onClick, className, as('button')"
                ),
            },
            "Input": {
                "description": (
                    "Text / textarea / password / number / email / tel input with label, "
                    "helpText, error state, and left/right icon slots."
                ),
                "key_props": (
                    "variant('text'|'textarea'|'password'|'number'|'email'|'tel'), "
                    "value, onChange(required), label, isRequired, isDisabled, error, "
                    "helpText, placeHolder, leftIcon, rightIcon, className"
                ),
            },
            "Dropdown": {
                "description": (
                    "Single or multi-select dropdown based on react-select. "
                    "Supports async API option loading via api prop, creatable options, "
                    "and custom label/value keys."
                ),
                "key_props": (
                    "value, onChange, options, label, isRequired, error, helpText, "
                    "placeholder, isMulti, isCreatable, onCreateOption, "
                    "api(UseApiOptions), labelKey, valueKey, apiEnabled, "
                    "apiResponseMapper, className"
                ),
            },
            "Checkbox": {
                "description": "Single checkbox. Use for one independent boolean value.",
                "key_props": (
                    "label(required, ReactNode), value(required), onChange(required), "
                    "isSelected, isDisabled, name, className"
                ),
            },
            "CheckboxGroup": {
                "description": (
                    "Group of checkboxes. Discriminated union on isMultiple: "
                    "when isMultiple=true value/onChange use arrays; "
                    "when isMultiple=false (default) value/onChange use a single value. "
                    "Supports async loading via api prop."
                ),
                "key_props": (
                    "options(required: {label, value, isDisabled?}[]), "
                    "value(required), onChange(required), isMultiple, "
                    "label, isRequired, isDisabled, error, helpText, direction('horizontal'|'vertical'), "
                    "api(UseApiOptions), labelKey, valueKey, apiResponseMapper, loadingComponent, className"
                ),
            },
            "Radio": {
                "description": (
                    "Group of radio options (exported as 'Radio'). "
                    "Supports async option loading via api prop."
                ),
                "key_props": (
                    "options(required: {value, label}[]), value(required), name(required), "
                    "onChange, label, isRequired, isDisabled, error, direction('horizontal'|'vertical'), "
                    "api(UseApiOptions), labelKey, valueKey, apiResponseMapper, loadingComponent, className"
                ),
            },
            "DatePicker": {
                "description": "Single date picker (react-datepicker wrapper). Supports time selection.",
                "key_props": (
                    "value(Date|null, required), onChange(required), label, isRequired, isDisabled, "
                    "error, helpText, placeholder, minDate, maxDate, dateFormat, showTimeSelect, icon, className"
                ),
            },
            "RangeDatePicker": {
                "description": "Start–end date range picker (separate component from DatePicker).",
                "key_props": (
                    "startDate(Date|null, required), endDate(Date|null, required), onChange(required), "
                    "label, isRequired, isDisabled, error, helpText, placeholder, "
                    "minDate, maxDate, dateFormat, icon, className"
                ),
            },
            "Table": {
                "description": (
                    "Sortable ag-Grid table with built-in pagination. "
                    "Use for embedded grids inside form / tab / popup. "
                    "NOT for the main full-page listing screen (use ConfigurableDashboard instead)."
                ),
                "key_props": (
                    "columnDefs(required), rowData, api(UseApiOptions), "
                    "tableId, tableName, tableWidth, tableHeight, className, "
                    "currentPage, totalRecords, totalPage, showPagination, "
                    "onPageNumberChange, onSelectionChanged(selectedRows: T[]), "
                    "onPaginationChanged(page: number), apiResponseMapper"
                ),
            },
            "List": {
                "description": (
                    "Scrollable card-based item list. Requires a CardComponent render prop. "
                    "Supports single or multi-select, async API loading, and custom layout."
                ),
                "key_props": (
                    "CardComponent(required: FC<{item, onChange?, selected?}>), "
                    "options, api(UseApiOptions), value, onChange, "
                    "isMultiSelect, isDisabled, isRequired, error, label, "
                    "scroll, scrollHeight, minHeight, layout({columns, gap, cardWidth, wrap}), "
                    "mapItem, apiResponseMapper, emptyComponent, loading, loadingComponent, className"
                ),
            },
            "FileUpload": {
                "description": "Drag-and-drop file upload (FilePond-based). Use for type=upload_zone or field type='fileUpload'.",
                "key_props": (
                    "label, helpText, error, isRequired, disabled, icon, "
                    "labelIdle(ReactNode), placeholder, className, "
                    "plus all FilePondProps (allowMultiple, acceptedFileTypes, maxFiles, onupdatefiles, etc.)"
                ),
            },
            "Map": {
                "description": (
                    "Google Maps location picker. Returns a structured address object. "
                    "Use keyMap to rename output keys to match form field names."
                ),
                "key_props": (
                    "apiKey(required), onChange(required), value(TExternal|null), "
                    "keyMap(AddressKeyMap — partial map of: formattedAddress, lat, lng, placeId, postalCode, city, state, country), "
                    "height, zoom, enableMarkerMove, className"
                ),
            },
            "Modal": {
                "description": (
                    "Overlay dialog. Use as outer shell for modal form screens. "
                    "Sizes: sm, md, lg, full."
                ),
                "key_props": (
                    "show(required), title(required, string), onClose(required), "
                    "size('sm'|'md'|'lg'|'full'), children, footer(ReactNode), "
                    "hasCloseButton, className"
                ),
            },
            "FormFieldWrapper": {
                "description": (
                    "Wraps any custom input with label, helpText, error, isRequired, isDisabled. "
                    "Use for custom fields rendered outside ConfigurableForm."
                ),
                "key_props": (
                    "children(required), label(ReactNode), helpText, error, "
                    "isRequired, isDisabled, className"
                ),
            },
            "Badge": {
                "description": (
                    "Status / label badge with auto-contrast text (WCAG AA). "
                    "Uses chroma-js for background color and getMinContrastForeground for text. "
                    "Use for KPI tiles, scan feedback states, and feedback_area banners."
                ),
                "key_props": (
                    "text(required), color(hex string, optional), size('sm'|'md'|'lg', default 'md'), "
                    "className, style(CSSProperties)"
                ),
            },
            "TabNav": {
                "description": (
                    "Horizontal tab navigation with lazy/keepAlive content panel rendering. "
                    "Controlled (activeId + onChange) or uncontrolled (defaultActiveId). "
                    "Each TabItem may carry inline content or delegate to renderActiveContent."
                ),
                "key_props": (
                    "tabs(required: TabItem[{id(string|number), label(string), icon?, badge?, disabled?, content?}]), "
                    "activeId, onChange(id: TabId), defaultActiveId, "
                    "lazy(boolean, default true), keepAlive(boolean, default false), "
                    "className, listClassName, itemClassName, activeItemClassName, "
                    "badgeClassName, contentClassName, renderTab, renderActiveContent"
                ),
            },
            "ToggleButton": {
                "description": "On/off toggle (e.g. show/hide columns). Already built into ConfigurableDashboard.",
                "key_props": (
                    "label(ReactNode), isActive, onChange, "
                    "onIcon(ReactNode), offIcon(ReactNode), "
                    "size('small'|'medium'|'large'), activeColor, inactiveColor, className"
                ),
            },
            "FilterModal": {
                "description": (
                    "Pre-built advanced filter dialog. "
                    "ALREADY BUNDLED inside ConfigurableDashboard — do NOT import or render it "
                    "separately when the screen uses ConfigurableDashboard."
                ),
                "key_props": (
                    "isOpen(required), onClose(required), onApplyFilter(required), "
                    "onClearFilter(required), selectedFilters(FilterItem[{field,type,value,group}]), "
                    "filterTitle(ReactNode), fieldInfo, fieldTypeInfo, "
                    "booleanOptions, customBooleanOptions, className"
                ),
            },
            "FilterChip": {
                "description": "Removable filter tag chip shown above a grid or filter bar.",
                "key_props": (
                    "label(required), color, selected, removable, onClick, onRemove"
                ),
            },
            "MultipleItem": {
                "description": (
                    "Dynamic multi-row form component. Renders a schema-driven list of rows "
                    "where each row contains one or more typed fields "
                    "(input | select | checkbox | radio | fileUpload). "
                    "Rows can be added and removed. Emits the full rows array on every change. "
                    "NOT a tag/chip input — it is a repeatable structured row editor."
                ),
                "when_to_use": [
                    "User needs to add multiple structured rows (e.g. invoice lines, BOM entries)",
                    "Each row has multiple fields of mixed types",
                    "Row count is dynamic (add / remove)",
                ],
                "key_props": (
                    "label(required, string), fields(required: MultiFieldSchema[]), "
                    "onChange(required: (rows: Record<string,any>[]) => void), "
                    "initialRows(Array<Record<string,any>|DynamicRow>?), "
                    "error(string?), className(string?)"
                ),
                "MultiFieldSchema_types": (
                    "Each field: { name, type('input'|'select'|'checkbox'|'radio'|'fileUpload'), label?, colSpan?, rowSpan? }. "
                    "type='input' extends InputProps (minus value/onChange/name/label). "
                    "type='select' extends DropdownProps (minus value/onChange/name/label). "
                    "type='checkbox' extends CheckboxGroupProps (minus value/onChange/label/name). "
                    "type='radio' extends RadioProps (minus value/onChange/label). "
                    "type='fileUpload' extends FileUploadProps (minus onFileChange/label/name)."
                ),
            },
        },
    },

    # ── data-layer ────────────────────────────────────────────────────────────
    "data-layer": {
        "import_path": "@msbc/data-layer",
        "description": (
            "API plumbing: typed axios wrapper, token management, RTK slice "
            "factory, and a generic React hook. Use whenever a module "
            "fetches or mutates server data."
        ),
        "exports": {
            "useApiRequest": (
                "Primary hook for GET/POST/PUT/DELETE/PATCH. "
                "Signature: useApiRequest<TResponse, TParams, TBody>(UseApiOptions) "
                "→ { data: TResponse|null, loading: boolean, apiError: ApiError|undefined, execute }. "
                "execute(override?) triggers an imperative call and returns Promise<TResponse>. "
                "UseApiOptions: { url, method?('get'|'post'|'put'|'delete'|'patch'), "
                "params?, body?, config?, autoFetch?(default true), isMultipart? }. "
                "NOTE: returns 'apiError' (not 'error') and 'execute' (not 'refetch')."
            ),
            "createApiSlice": (
                "RTK createSlice factory for Redux-cached endpoints. "
                "createApiSlice<TResponse, TRequestBody, TParams>(name, endpoint, method?, configParams?) "
                "→ { reducer, actions: { fetchData } }. "
                "Prefer for shared / frequently-invalidated data accessed by multiple components."
            ),
            "apiClient": (
                "Typed axios wrapper for one-off imperative calls. "
                "Methods: get<T>(url, params?, config?), post<T>(url, body?, config?), "
                "put<T>(url, body?, config?), patch<T>(url, body?, config?), "
                "delete<T>(url, body?, config?). All return Promise<T> with response.data already unwrapped."
            ),
            "createTokenManager": (
                "Factory that returns a token manager instance. "
                "createTokenManager(opts?) → { setTokens, getAccessToken, getRefreshToken, "
                "clearTokens, isAuthenticated, refreshAccessToken, getAllTokens, setRefreshEndpoint }. "
                "Options: storage(Storage), accessKey, refreshKey, refreshEndpoint, fetcher."
            ),
            "UseApiOptions": (
                "Type: { url: string; method?: 'get'|'post'|'put'|'delete'|'patch'; "
                "params?: TParams; body?: TBody; config?: ApiRequestConfig; "
                "autoFetch?: boolean; isMultipart?: boolean }. "
                "Used as the api? prop on Dropdown, CheckboxGroup, RadioGroup, Table, List."
            ),
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
            "useApiRequest returns { data, loading, apiError, execute } — NOT { data, loading, error, refetch }",
        ],
    },

    # ── utils ─────────────────────────────────────────────────────────────────
    "utils": {
        "import_path": "@msbc/utils",
        "description": "Shared utility functions and helpers used across all packages.",
        "exports": {
            "classname": (
                "BEM class-name builder (withNaming from @bem-react/classname). "
                "Usage: const cn = classname('block'); cn() → 'block'; "
                "cn('elem') → 'block__elem'; cn('elem', { mod: true }) → 'block__elem block__elem--mod'; "
                "cn('elem', { color: 'red' }) → 'block__elem block__elem--color-red'."
            ),
            "classnames": "The 'classnames' library. Build conditional class lists from strings, objects, or arrays.",
            "cns": "Alias for classnames. Shorthand for conditional class composition.",
            "isEmpty": (
                "Returns true for: null, undefined, empty string (after trim), "
                "empty array, empty object. Signature: isEmpty(value: any) → boolean."
            ),
            "useDebounce": (
                "Returns a debounced copy of a reactive value. "
                "Signature: useDebounce<T>(value: T, delay?: number = 300) → T."
            ),
            "useDebouncedCallback": (
                "Returns a debounced version of a callback. "
                "Signature: useDebouncedCallback<T extends (...args) => any>(callback: T, delay?: number = 300) → T."
            ),
            "getMinContrastForeground": (
                "Given a background hex color, returns a foreground CSS color meeting WCAG AA (4.5:1 contrast). "
                "Used internally by Badge."
            ),
            "getContrastRatio": "Computes contrast ratio between two hex colors.",
            "MIN_CONTRAST_RATIO": "WCAG AA minimum contrast constant (4.5).",
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
                    "Config-driven three-step import wizard: "
                    "(1) module selection form, (2) file upload form, (3) FieldMapper. "
                    "Drives all steps via a single `config: ImportWizardConfig` object "
                    "that specifies API endpoints, ConfigurableForm configs, response mappers, "
                    "and labels. Emits onSuccess / onError callbacks."
                ),
                "when_to_use": [
                    "Module needs to import data from a CSV or Excel file",
                    "Module needs a guided column-to-field mapping step",
                    "Module needs server-side header extraction before mapping",
                ],
                "key_props": {
                    "config": "ImportWizardConfig (required)",
                },
                "ImportWizardConfig_fields": {
                    "labels": "{ module: string; upload: string; mapping: string; fieldMapperLabels: FieldMapperLabels }",
                    "apis.fetchModules": "{ url, method?('get'|'post'), responseMapper?(response) → any[] }",
                    "apis.extractHeaders": "{ url, method?('post'), buildRequest?(data, formData) → FormData }",
                    "apis.submitMapping": "{ url, method?('post'), buildRequest?(mapping, headerId) → any }",
                    "forms.module": "JSONFormSchema config — module-selection form",
                    "forms.upload": "JSONFormSchema config — file-upload form",
                    "responseMapper.headers": "(response) → { id: string; sourceFields: string[]; systemFields: string[]; suggestedMapping?: Record<string,string> }",
                    "onSuccess": "(response: any) => void?",
                    "onError": "(error: any) => void?",
                    "stepperProps": "Omit<StepperProps, 'steps'|'activeStep'>?",
                },
                "internally_uses": ["FieldMapper", "ConfigurableForm", "useApiRequest"],
                "data_layer_hooks": ["useApiRequest"],
            },
            "FieldMapper": {
                "description": (
                    "Standalone field-mapping table: maps source CSV columns to system fields. "
                    "Can be used independently of ImportWizard when only the mapping step is needed."
                ),
                "when_to_use": [
                    "Screen only needs the column-mapping step (no wizard flow)",
                ],
                "key_props": (
                    "sourceFields(required: string[]), systemFields(required: string[]), "
                    "onSubmit(required: (mapping: Record<string,string>) => void), "
                    "onBack(() => void?), requiredSystemFields(string[]?), isSubmitting(boolean?), "
                    "labels(FieldMapperLabels?: { title, targetColumn, sourceColumn, submitButton, backButton, requiredError })"
                ),
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
                "key_props": (
                    "routes(required: { path: string; title: string; component: string; config?: string }[]), "
                    "components(required: Record<string, React.FC<any>>), "
                    "header(ReactNode?), sidebar(ReactNode?)"
                ),
                "when_to_use": [
                    "Top-level entry point that owns the BrowserRouter and full layout",
                    "Route list is data-driven (JSON config)",
                ],
            },
            "LayoutRoute": {
                "description": (
                    "Header + sidebar layout with a React Router <Outlet />. "
                    "Use inside an existing Router when AppShell's BrowserRouter "
                    "is not wanted (e.g. inside a micro-frontend that shares a Router)."
                ),
                "key_props": "header(ReactNode?), sidebar(ReactNode?)",
            },
            "ShellRoutes": {
                "description": (
                    "Declarative <Routes> renderer. Maps a routes[] config array "
                    "to components without owning a Router or layout. "
                    "Use when you already have a Router and layout and only need "
                    "the route → component wiring."
                ),
                "key_props": (
                    "routes(required: ShellRoute[{ path: string; component: string; title?: string; config?: string; index?: boolean }]), "
                    "components(required: Record<string, React.FC<any>>)"
                ),
            },
        },
    },
}


# ─── Component type → toolkit mapping ────────────────────────────────────────
# Deterministic lookup: component type → exact toolkit_mapping string for the LLM.

COMPONENT_TYPE_MAPPING: dict[str, str] = {
    "toolbar":          "Button",                    # one Button per action; no Toolbar primitive
    "grid":             "ConfigurableDashboard",     # full-page listing screen
    "grid_embedded":    "Table",                     # grid inside form / tab / popup
    "form":             "ConfigurableForm",          # modal or full-page data-entry form
    "form_simple":      "Input, Dropdown",           # 1-2 inline fields, no full form engine
    "filter_panel":     "FilterModal",               # dialog-style (non-dashboard screens only)
    "filter_inline":    "Dropdown, RangeDatePicker", # inline chip-style filters
    "tabs":             "TabNav",
    "info_panel":       "Input",                     # readonly=true display fields
    "scan_panel":       "Input",                     # single barcode/RFID field + Badge feedback
    "kpi":              "Badge",                     # count/status summary tiles, no mutation
    "upload_zone":      "FileUpload",
    "import_wizard":    "ImportWizard",              # CSV/Excel guided import flow
    "stepper":          "Button, Modal",             # no Stepper primitive — model with step index state
    "feedback_area":    "Badge",                     # no Toast/Snackbar — Badge or styled div
    "barcode_panel":    "Input, Button",             # display barcode + print/download
    "multi_row_form":   "MultipleItem",              # dynamic add/remove rows of typed fields
}


# ─── Strict field / filter type tables ───────────────────────────────────────

ALLOWED_FIELD_TYPES: list[str] = [
    "text", "email", "number", "password", "textarea", "tel",
    "select", "radio", "checkbox", "list",
    "fileUpload", "map", "date", "date-range", "custom",
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
    "upload":       "fileUpload",
    "file":         "fileUpload",
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
    "number":       "int",
    "checkbox":     "bool",
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


# ─── Common gotchas ───────────────────────────────────────────────────────────

COMMON_MISTAKES: list[str] = [
    "useApiRequest returns { data, loading, apiError, execute } — NOT { error } or { refetch }.",
    "MultipleItem is a dynamic multi-row form editor, NOT a tag/chip input.",
    "ConfigurableDashboard.config.api goes at top level of DashboardConfig, never inside tableProps.",
    "Radio/RadioGroup is exported as 'Radio' from @msbc/react-toolkit — import { Radio } not { RadioGroup }.",
    "CheckboxGroup with isMultiple=true expects value: (string|number|boolean)[] and onChange receiving an array.",
    "FilterModal is already bundled inside ConfigurableDashboard — do NOT import or render it separately on dashboard screens.",
    "Pagination is already inside Table/ConfigurableDashboard — do NOT add it separately.",
    "ConfigurableForm field type 'select' renders Dropdown; 'checkbox' renders CheckboxGroup; 'radio' renders Radio.",
    "DependsConfig.fieldName is the parent field key (the field whose change triggers this field), NOT this field's own name.",
    "FormSectionGroup requires type: 'group' as a required literal string — it is NOT optional.",
    "VisibilityRule group operator is 'AND' or 'OR' (uppercase), not 'and'/'or'.",
    "TabNav prop is 'tabs' (TabItem[]) — each item needs 'id' (string|number) and 'label' (string).",
    "Map.keyMap renames address output keys — use it when form field names differ from InternalAddressResult keys.",
    "apiClient methods return Promise<TResponse> with response.data already unwrapped (not the raw AxiosResponse).",
    "ConfigurableForm 'custom' field type requires component or render prop — it does NOT auto-render from type alone.",
    "DashboardConfig filters[].type uses 'select' (not 'dropdown') and 'date-range' (not 'date_range').",
]


# ─── Prompt-ready context builder ─────────────────────────────────────────────

def build_toolkit_context() -> str:
    """
    Returns a compact, token-efficient description of the MSBC toolkit for
    injection into planner prompts.  Includes:
      - Per-package component/export listings with prop types and guidance
      - Component type → toolkit_mapping lookup table
      - Strict field/filter type tables with forbidden aliases
      - File structure conventions
      - Common mistakes to avoid
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
                    if "description" in meta:
                        lines.append(f"    {meta['description']}")
                    if "when_to_use" in meta:
                        lines.append(f"    USE WHEN: {' | '.join(meta['when_to_use'])}")
                    if "do_not_use_when" in meta:
                        lines.append(f"    DO NOT USE: {' | '.join(meta['do_not_use_when'])}")
                    if "key_props" in meta:
                        if isinstance(meta["key_props"], dict):
                            props_str = "; ".join(f"{k}: {v}" for k, v in meta["key_props"].items())
                        else:
                            props_str = meta["key_props"]
                        lines.append(f"    key_props: {props_str}")
                    if "MultiFieldSchema_types" in meta:
                        lines.append(f"    MultiFieldSchema: {meta['MultiFieldSchema_types']}")
                    if "DashboardConfig_fields" in meta:
                        lines.append("    DashboardConfig fields:")
                        for k, v in meta["DashboardConfig_fields"].items():
                            lines.append(f"      {k}: {v}")
                    if "ImportWizardConfig_fields" in meta:
                        lines.append("    ImportWizardConfig fields:")
                        for k, v in meta["ImportWizardConfig_fields"].items():
                            lines.append(f"      {k}: {v}")
                    if "JSONFormSchema_fields" in meta:
                        lines.append("    JSONFormSchema fields:")
                        for k, v in meta["JSONFormSchema_fields"].items():
                            lines.append(f"      {k}: {v}")
                    if "FormSection_fields" in meta:
                        lines.append("    FormSection fields:")
                        for k, v in meta["FormSection_fields"].items():
                            lines.append(f"      {k}: {v}")
                    if "FormSectionGroup_fields" in meta:
                        lines.append("    FormSectionGroup fields:")
                        for k, v in meta["FormSectionGroup_fields"].items():
                            lines.append(f"      {k}: {v}")
                    if "BaseField_props" in meta:
                        lines.append("    BaseField props:")
                        for k, v in meta["BaseField_props"].items():
                            lines.append(f"      {k}: {v}")
                    if "ValidationRule_props" in meta:
                        lines.append("    ValidationRule props:")
                        for k, v in meta["ValidationRule_props"].items():
                            lines.append(f"      {k}: {v}")
                    if "DependsConfig_props" in meta:
                        lines.append("    DependsConfig props:")
                        for k, v in meta["DependsConfig_props"].items():
                            lines.append(f"      {k}: {v}")
                    if "VisibilityRule_operators" in meta:
                        lines.append(f"    visibleIf operators: {' | '.join(meta['VisibilityRule_operators'])}")
                    if "field_types" in meta:
                        lines.append(f"    field types: {' | '.join(meta['field_types'])}")
                    if "key_config_rules" in meta:
                        lines.append(f"    config rules: {' | '.join(meta['key_config_rules'])}")
                    if "data_layer_hooks" in meta:
                        lines.append(f"    data_hook: {', '.join(meta['data_layer_hooks'])}")
                    if "internally_uses" in meta:
                        lines.append(f"    internally_uses: {', '.join(meta['internally_uses'])}")
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
        lines.append(f"  {ctype:<20} → {mapping}")

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

    # ── Common mistakes ───────────────────────────────────────────────────
    lines += [
        "",
        "─────────────────────────────────────────────────────",
        "COMMON MISTAKES — NEVER DO THESE",
        "─────────────────────────────────────────────────────",
    ]
    for mistake in COMMON_MISTAKES:
        lines.append(f"  ✗ {mistake}")

    # ── Decision guide ────────────────────────────────────────────────────
    lines += [
        "",
        "─────────────────────────────────────────────────────",
        "DECISION GUIDE",
        "─────────────────────────────────────────────────────",
        "  Full listing page (opens_as=page)       → ConfigurableDashboard + useApiRequest (internal to config)",
        "  Create / edit form (modal or page)      → ConfigurableForm + useApiRequest",
        "  Embedded sub-grid (tab/popup/form)      → Table + useApiRequest",
        "  Dynamic multi-row data entry            → MultipleItem (NOT a tag input)",
        "  CSV/Excel guided import flow            → ImportWizard (@msbc/import-utils)",
        "  Field mapping only (no wizard)          → FieldMapper (@msbc/import-utils)",
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
