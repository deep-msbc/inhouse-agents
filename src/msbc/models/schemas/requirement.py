"""
Pydantic request/response schemas for the Requirement Extractor API.

Request  : ParseRequest  — form fields validated by FastAPI before the handler runs.
Response : ParseResponse — typed response returned by POST /requirement-extractor/parse.

Structure overview
──────────────────
ParseResponse
├── extraction : ExtractionResult  (discriminated union on "mode")
│   │
│   ├── FrontendExtractionResult   mode="frontend"
│   │   └── modules: list[FrontendModuleItem]
│   │       ├── name, order, description
│   │       ├── screens: list[FrontendScreen]
│   │       │   ├── components: list[FrontendComponent]
│   │       │   ├── field_groups: list[FrontendFieldGroup]
│   │       │   │   └── fields: list[FrontendField]
│   │       │   ├── actions: list[FrontendScreenAction]
│   │       │   └── behaviors: list[FrontendBehavior]
│   │       ├── enums: list[EnumItem]
│   │       ├── business_rules: list[str]
│   │       └── workflows: list[FrontendWorkflow]
│   │
│   ├── BackendExtractionResult    mode="backend"
│   │   └── modules: list[BackendModuleItem]
│   │       ├── name, order, description
│   │       ├── api_endpoints: list[ApiEndpoint]
│   │       │   ├── request_params: BackendRequestParams
│   │       │   │   └── path|query|body: list[BackendParamItem]
│   │       │   ├── response_body: BackendResponseBody
│   │       │   │   └── fields: list[BackendResponseBodyField]
│   │       │   └── error_responses: list[BackendErrorResponse]
│   │       ├── models: list[DbModel]
│   │       │   ├── fields: list[DbField]
│   │       │   └── relationships: list[DbRelationship]
│   │       ├── business_logic: list[BusinessLogicItem]
│   │       └── workflows: list[BackendWorkflow]
│   │
│   └── BothExtractionResult       mode="both"
│       └── modules: list[BothModuleItem]
│           ├── name, order, description
│           ├── frontend: BothFrontendSection
│           │   ├── screens: list[FrontendScreen]
│           │   ├── enums: list[EnumItem]
│           │   ├── business_rules: list[str]
│           │   └── workflows: list[FrontendWorkflow]
│           └── backend: BothBackendSection
│               ├── api_endpoints: list[ApiEndpoint]
│               ├── models: list[DbModel]
│               ├── business_logic: list[BusinessLogicItem]
│               └── workflows: list[BackendWorkflow]
│
├── graph : DependencyGraph
│   ├── nodes: list[GraphNode]
│   ├── edges: list[GraphEdge]
│   ├── entry_points: list[str]
│   └── metadata: GraphMetadata
│
└── usage : LLMUsage
    ├── input_tokens, output_tokens, total_tokens
    ├── input_cost_usd, output_cost_usd, total_cost_usd
    └── model

Design decisions
────────────────
* All extraction sub-models inherit ``_OpenModel`` (extra="allow") so that
  LLM output fields not listed here are kept rather than rejected.
* The top-level ``ExtractionResult`` is a discriminated union on the ``mode``
  field ("frontend" | "backend" | "both").  Pydantic v2 picks the correct
  branch automatically and validates accordingly.
* The JSON-Schema layer (agents/schemas/) validates the raw LLM string before
  Pydantic runs.  These schemas are complementary: JSON Schema catches shape
  errors early; Pydantic gives typed Python objects and Swagger documentation.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ─────────────────────────────────────────────────────────────────────────────
# Base
# ─────────────────────────────────────────────────────────────────────────────

class _OpenModel(BaseModel):
    """Base for all extraction sub-models — extra keys from the LLM are kept."""
    model_config = ConfigDict(extra="allow")


# ─────────────────────────────────────────────────────────────────────────────
# Shared across modes
# ─────────────────────────────────────────────────────────────────────────────

class EnumItem(_OpenModel):
    """A named enumeration defined in the user story (e.g. OrderStatus)."""
    name: str
    values: list[str] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Frontend sub-models
# ─────────────────────────────────────────────────────────────────────────────

class FrontendField(_OpenModel):
    """A single form / input field on a screen."""
    name: str
    label: str | None = None
    type: str | None = None                  # e.g. "text", "date", "dropdown"
    required: bool | None = None
    default_value: Any = None
    placeholder: str | None = None
    options: list[Any] = Field(default_factory=list)
    validation: list[str] = Field(default_factory=list)
    readonly: bool | None = None
    depends_on: str | None = None
    visible_when: str | None = None
    required_when: str | None = None
    disabled_when: str | None = None
    computed_formula: str | None = None
    auto_fill_from: str | None = None
    behavior: str | None = None


class FrontendFieldGroup(_OpenModel):
    """A named group of form fields (e.g. 'Shipment Details')."""
    group_name: str
    fields: list[FrontendField] = Field(default_factory=list)


class FrontendScreenAction(_OpenModel):
    """A button / CTA on a screen (e.g. 'Save', 'Cancel', 'Submit')."""
    label: str
    type: str | None = None          # e.g. "primary", "secondary", "danger"
    behavior: str | None = None      # e.g. "submit_form", "navigate_back"
    disabled_when: str | None = None
    opens_screen: str | None = None  # target screen name, if applicable


class FrontendBehavior(_OpenModel):
    """A conditional UI behaviour rule on a screen."""
    trigger: str | None = None       # e.g. "on_field_change:status"
    action: str | None = None        # e.g. "show_field:reason"
    condition: str | None = None


class FrontendComponent(_OpenModel):
    """
    A UI component on a dashboard screen.

    ``type`` is the only guaranteed field (e.g. "toolbar", "grid", "kpi",
    "tabs", "form", "scan_panel", "stepper", "filter_panel", "upload_zone",
    "barcode_panel", "feedback_area", "timeline", "info_panel", …).

    All component-type-specific internals (actions, columns, children, kpis,
    filters, field_groups, feedback_states, …) are kept as extra fields because
    each component type has a completely different shape.
    """
    type: str
    id: str | None = None


class FrontendScreen(_OpenModel):
    """
    One screen in the module.  Two shapes are supported:

    dashboard — content lives inside ``components``.
    form      — content may live in ``field_groups`` / ``actions`` /
                ``validations`` / ``behaviors``, or inside a nested form
                component.  Both representations are valid.
    """
    name: str
    screen_type: str                 # "dashboard" | "form" | any future type
    opens_as: str | None = None      # e.g. "page", "modal", "drawer"
    purpose: str | None = None
    title: str | None = None
    description: str | None = None
    linked_forms: list[str] = Field(default_factory=list)
    # Dashboard shape
    components: list[FrontendComponent] = Field(default_factory=list)
    # Form shape — may appear at screen level or inside a form component
    field_groups: list[FrontendFieldGroup] = Field(default_factory=list)
    actions: list[FrontendScreenAction] = Field(default_factory=list)
    validations: list[str] = Field(default_factory=list)
    behaviors: list[FrontendBehavior] = Field(default_factory=list)


class FrontendWorkflow(_OpenModel):
    """A user-facing workflow spanning multiple screens."""
    name: str
    steps: list[str] = Field(default_factory=list)
    screens_involved: list[str] = Field(default_factory=list)


class FrontendModule(_OpenModel):
    """All frontend data extracted for one module."""
    name: str
    description: str | None = None
    screens: list[FrontendScreen] = Field(default_factory=list)
    enums: list[EnumItem] = Field(default_factory=list)
    business_rules: list[str] = Field(default_factory=list)
    workflows: list[FrontendWorkflow] = Field(default_factory=list)


class FrontendExtraction(_OpenModel):
    """
    The LLM response envelope for mode='frontend'.
    Shape: ``{"module": { ... }}``
    """
    module: FrontendModule


# ─────────────────────────────────────────────────────────────────────────────
# Backend sub-models
# ─────────────────────────────────────────────────────────────────────────────

class BackendParamItem(_OpenModel):
    """A single request parameter (path, query, or body)."""
    name: str
    type: str
    required: bool | None = None
    validation: str | None = None
    notes: str | None = None


class BackendRequestParams(_OpenModel):
    """All request parameters for an endpoint, grouped by location."""
    path: list[BackendParamItem] = Field(default_factory=list)
    query: list[BackendParamItem] = Field(default_factory=list)
    body: list[BackendParamItem] = Field(default_factory=list)


class BackendResponseBodyField(_OpenModel):
    """A single field in an endpoint's success response body."""
    name: str
    type: str
    notes: str | None = None


class BackendResponseBody(_OpenModel):
    """Describes the success response of an API endpoint."""
    success_status: int | None = None
    shape: str | None = None         # e.g. "object", "array", "file_download", "paginated"
    fields: list[BackendResponseBodyField] = Field(default_factory=list)


class BackendErrorResponse(_OpenModel):
    """One error case listed in an endpoint's error_responses."""
    status: int
    condition: str


class ApiEndpoint(_OpenModel):
    """A single REST API endpoint."""
    path: str
    method: str                       # e.g. "GET", "POST", "PUT", "DELETE", "PATCH"
    summary: str
    request_params: BackendRequestParams | None = None
    response_body: BackendResponseBody | None = None
    authentication: str | None = None
    authorization: str | None = None
    validations: list[str] = Field(default_factory=list)
    error_responses: list[BackendErrorResponse] = Field(default_factory=list)
    notes: str | None = None


class DbField(_OpenModel):
    """A database model column / field."""
    name: str
    type: str                         # e.g. "string", "integer", "datetime"
    required: bool | None = None
    unique: bool | None = None
    default: str | int | float | bool | None = None
    enum_values: list[str] | None = None
    max_length: str | int | None = None
    notes: str | None = None


class DbRelationship(_OpenModel):
    """A relationship between two database models."""
    type: str                         # e.g. "belongs_to", "has_many", "many_to_many"
    target_model: str
    foreign_key: str | None = None
    description: str | None = None


class DbModel(_OpenModel):
    """A database model / entity."""
    name: str
    description: str | None = None
    table_name: str | None = None
    fields: list[DbField] = Field(default_factory=list)
    relationships: list[DbRelationship] = Field(default_factory=list)
    indexes: list[str] = Field(default_factory=list)
    soft_delete: bool | str | None = None


class BusinessLogicItem(_OpenModel):
    """A single business rule or constraint."""
    rule: str
    trigger: str | None = None
    affected_entities: list[str] = Field(default_factory=list)
    enforcement: str | None = None   # e.g. "application", "database", "both"


class BackendWorkflow(_OpenModel):
    """A backend process or workflow (e.g. order fulfilment, approval chain)."""
    name: str
    trigger: str | None = None
    steps: list[str] = Field(default_factory=list)
    outcome: str | None = None
    rollback: str | None = None


class BackendModule(_OpenModel):
    """All backend data extracted for one module."""
    name: str
    description: str | None = None
    api_endpoints: list[ApiEndpoint] = Field(default_factory=list)
    models: list[DbModel] = Field(default_factory=list)
    business_logic: list[BusinessLogicItem] = Field(default_factory=list)
    workflows: list[BackendWorkflow] = Field(default_factory=list)


class BackendExtraction(_OpenModel):
    """
    The LLM response envelope for mode='backend'.
    Shape: ``{"module": { ... }}``
    """
    module: BackendModule


# ─────────────────────────────────────────────────────────────────────────────
# Combined / both sub-models
# ─────────────────────────────────────────────────────────────────────────────

class BothFrontendSection(_OpenModel):
    """
    The frontend section inside a combined (mode='both') module.
    Reuses the same leaf types as the standalone frontend extraction.
    """
    screens: list[FrontendScreen] = Field(default_factory=list)
    enums: list[EnumItem] = Field(default_factory=list)
    business_rules: list[str] = Field(default_factory=list)
    workflows: list[FrontendWorkflow] = Field(default_factory=list)


class BothBackendSection(_OpenModel):
    """
    The backend section inside a combined (mode='both') module.
    Reuses the same leaf types as the standalone backend extraction.
    """
    api_endpoints: list[ApiEndpoint] = Field(default_factory=list)
    models: list[DbModel] = Field(default_factory=list)
    business_logic: list[BusinessLogicItem] = Field(default_factory=list)
    workflows: list[BackendWorkflow] = Field(default_factory=list)


class BothModule(_OpenModel):
    """Module data for mode='both' — carries both frontend and backend sections."""
    name: str
    description: str | None = None
    frontend: BothFrontendSection = Field(default_factory=BothFrontendSection)
    backend: BothBackendSection = Field(default_factory=BothBackendSection)


class BothExtraction(_OpenModel):
    """
    The LLM response envelope for mode='both'.
    Shape: ``{"module": {"name": ..., "frontend": {...}, "backend": {...}}}``
    """
    module: BothModule


# ─────────────────────────────────────────────────────────────────────────────
# Module-level items — one entry per module in the finalize_node output
# ─────────────────────────────────────────────────────────────────────────────

class FrontendModuleItem(_OpenModel):
    """One module's frontend extraction in the finalize_node output."""
    name: str
    order: int | None = None
    description: str | None = None
    screens: list[FrontendScreen] = Field(default_factory=list)
    enums: list[EnumItem] = Field(default_factory=list)
    business_rules: list[str] = Field(default_factory=list)
    workflows: list[FrontendWorkflow] = Field(default_factory=list)


class BackendModuleItem(_OpenModel):
    """One module's backend extraction in the finalize_node output."""
    name: str
    order: int | None = None
    description: str | None = None
    api_endpoints: list[ApiEndpoint] = Field(default_factory=list)
    models: list[DbModel] = Field(default_factory=list)
    business_logic: list[BusinessLogicItem] = Field(default_factory=list)
    workflows: list[BackendWorkflow] = Field(default_factory=list)


class BothModuleItem(_OpenModel):
    """One module's combined extraction in the finalize_node output."""
    name: str
    order: int | None = None
    description: str | None = None
    frontend: BothFrontendSection = Field(default_factory=BothFrontendSection)
    backend: BothBackendSection = Field(default_factory=BothBackendSection)


# ─────────────────────────────────────────────────────────────────────────────
# Mode-specific extraction results  (discriminated union on "mode")
# ─────────────────────────────────────────────────────────────────────────────

class FrontendExtractionResult(_OpenModel):
    """Extraction envelope produced by finalize_node for mode='frontend'."""
    mode: Literal["frontend"]
    total_modules: int | None = None
    modules: list[FrontendModuleItem] = Field(default_factory=list)


class BackendExtractionResult(_OpenModel):
    """Extraction envelope produced by finalize_node for mode='backend'."""
    mode: Literal["backend"]
    total_modules: int | None = None
    modules: list[BackendModuleItem] = Field(default_factory=list)


class BothExtractionResult(_OpenModel):
    """Extraction envelope produced by finalize_node for mode='both'."""
    mode: Literal["both"]
    total_modules: int | None = None
    modules: list[BothModuleItem] = Field(default_factory=list)


# Pydantic v2 discriminated union — picks the correct branch on "mode" value.
ExtractionResult = Annotated[
    FrontendExtractionResult | BackendExtractionResult | BothExtractionResult,
    Field(discriminator="mode"),
]


# ─────────────────────────────────────────────────────────────────────────────
# Graph sub-models
# ─────────────────────────────────────────────────────────────────────────────

class GraphNode(_OpenModel):
    """A node in the module dependency graph."""
    id: str
    label: str
    type: str | None = None          # e.g. "feature", "auth", "data", "integration", "utility"
    description: str | None = None
    external_dependencies: list[str] = Field(default_factory=list)


class GraphEdge(_OpenModel):
    """A directed edge between two graph nodes."""
    from_: str = Field(..., alias="from")
    to: str
    relation: str                    # e.g. "depends_on", "calls", "triggers", "navigates_to"
    interaction_type: str | None = None
    data_shared: list[str] = Field(default_factory=list)
    description: str | None = None

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class GraphMetadata(_OpenModel):
    """Summary metadata attached to the graph."""
    total_modules: int | None = None
    mode: str | None = None
    total_edges: int | None = None


class DependencyGraph(_OpenModel):
    """The full module dependency graph produced by the graph builder."""
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    entry_points: list[str] = Field(default_factory=list)
    metadata: GraphMetadata | None = None


class GraphResponse(_OpenModel):
    """
    The graph builder LLM response envelope.
    Shape: ``{"graph": { ... }}``
    """
    graph: DependencyGraph | None = None


# ─────────────────────────────────────────────────────────────────────────────
# LLM usage
# ─────────────────────────────────────────────────────────────────────────────

class LLMUsage(BaseModel):
    """Aggregated token and cost usage across all LLM calls in the request."""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    input_cost_usd: float = 0.0
    output_cost_usd: float = 0.0
    total_cost_usd: float = 0.0
    model: str = ""

    model_config = ConfigDict(extra="ignore")


# ─────────────────────────────────────────────────────────────────────────────
# Top-level request / response
# ─────────────────────────────────────────────────────────────────────────────

class ParseRequest(BaseModel):
    """
    Validated form fields for POST /requirement-extractor/parse.

    FastAPI reads ``file`` as UploadFile and ``mode`` as a Form string;
    this model documents and validates the ``mode`` value only.
    """
    mode: Literal["frontend", "backend", "both"] = Field(
        default="both",
        description="Extraction mode: 'frontend', 'backend', or 'both'.",
    )

    @field_validator("mode", mode="before")
    @classmethod
    def normalise_mode(cls, v: str) -> str:
        return v.strip().lower()


class ParseResponse(BaseModel):
    """
    Typed HTTP 200 response for POST /requirement-extractor/parse.

    Fields
    ------
    status     — always ``"success"`` on HTTP 200.
    mode       — the extraction mode that was used.
    filename   — original uploaded filename.
    extraction — per-module structured requirements; shape depends on mode.
    graph      — module dependency graph (nodes + edges).
    usage      — aggregated LLM token / cost summary.
    """
    status: Literal["success"] = "success"
    mode: str
    filename: str
    extraction: ExtractionResult
    graph: DependencyGraph
    usage: LLMUsage

    model_config = ConfigDict(extra="allow")
