"""
Pydantic request / response schemas for the Frontend Planner Agent.

Request  : PlanRequest  — POST /frontend-planner/plan body.
Response : PlanResponse — typed HTTP 200 response.

Output model hierarchy (mirrors the LLM output contract):
  PlanResponse
  └── modules: list[ModulePlan]
      ├── screens: list[ScreenPlan]
      │   ├── components: list[ComponentPlan]
      │   │   ├── actions:    list[ActionPlan]
      │   │   ├── columns:    list[ColumnDef]
      │   │   ├── fields:     list[FieldDef]
      │   │   └── filters:    list[FilterDef]
      │   ├── user_interactions: list[UserInteraction]
      │   └── data_flow:     DataFlow
      │       ├── state:     list[StateItem]
      │       └── api_calls: list[ApiCall]
      ├── shared_components: list[SharedComponent]
      └── file_structure:    list[FilePlan]

Design:
  - All sub-models use ConfigDict(extra="allow") so unrecognised LLM fields are
    kept rather than rejected (mirrors the extractor's _OpenModel pattern).
  - Coercion validators normalise common LLM type mistakes (e.g. dict → JSON string).
  - LLMUsage is a local definition; the extraction-stage LLMUsage in
    models/schemas/requirement.py is a separate type scoped to that stage.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ─── Base ─────────────────────────────────────────────────────────────────────

class _OpenModel(BaseModel):
    """Base for all planner sub-models — extra LLM fields are kept."""
    model_config = ConfigDict(extra="allow")


# ─── Component level ──────────────────────────────────────────────────────────

class ActionPlan(_OpenModel):
    """A button / icon action inside a toolbar or form."""
    text: str
    type: str = ""                         # primary | secondary | icon | text
    behavior: str = ""                     # open_modal | export_table | refresh | submit | delete | …
    opens_component: Optional[str] = None  # target screen/component name


class ColumnDef(_OpenModel):
    """Rich column definition for a grid component."""
    name: str                              # camelCase — maps to columnDef.field
    label: str                             # display header — maps to columnDef.headerName
    type: str = "text"                     # text | number | boolean | date | badge | status_chip | …
    sortable: bool = True
    editable: bool = False
    format: Optional[str] = None
    color_logic: Optional[str] = None

    @field_validator("color_logic", mode="before")
    @classmethod
    def _coerce_color_logic(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        if isinstance(v, dict):
            return json.dumps(v)
        return str(v)


class FieldDef(_OpenModel):
    """Rich field definition for a form / filter_panel component."""
    name: str
    label: str
    type: str = "text"                     # MUST be one of ALLOWED_FIELD_TYPES
    required: bool = False
    options: List[str] = Field(default_factory=list)      # required for select/radio/checkbox
    validation: List[str] = Field(default_factory=list)
    visible_when: Optional[str] = None
    required_when: Optional[str] = None
    disabled_when: Optional[str] = None
    default_value: Optional[str] = None
    behavior: Optional[str] = None

    @field_validator("default_value", mode="before")
    @classmethod
    def _coerce_default_value(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        if isinstance(v, (int, float, bool)):
            return str(v)
        if isinstance(v, (list, dict)):
            return json.dumps(v)
        return str(v)


class FilterDef(_OpenModel):
    """Rich filter definition for a filter_panel component."""
    name: str
    label: str
    type: str = "text"                     # MUST be one of ALLOWED_FILTER_TYPES
    options: List[str] = Field(default_factory=list)
    default_value: Optional[str] = None
    placeholder: Optional[str] = None

    @field_validator("default_value", mode="before")
    @classmethod
    def _coerce_default_value(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        if isinstance(v, (int, float, bool)):
            return str(v)
        if isinstance(v, (list, dict)):
            return json.dumps(v)
        return str(v)


class ComponentPlan(_OpenModel):
    """Plan for one UI component on a screen."""
    component_name: str
    type: str                              # toolbar | grid | form | filter_panel | tabs | kpi | …
    toolkit_mapping: str                   # exact value from COMPONENT_TYPE_MAPPING
    similarity_query: str                  # component-level vector search query

    # toolbar-specific
    actions: List[ActionPlan] = Field(default_factory=list)

    # grid-specific
    columns: List[ColumnDef] = Field(default_factory=list)

    # form-specific
    fields: List[FieldDef] = Field(default_factory=list)
    validations: List[str] = Field(default_factory=list)  # form-level cross-field rules

    # filter-specific
    filters: List[FilterDef] = Field(default_factory=list)

    data_hook: str = ""                    # useApiRequest | createApiSlice | ""


# ─── Screen level ─────────────────────────────────────────────────────────────

class UserInteraction(_OpenModel):
    """One end-to-end user-initiated workflow within a screen."""
    action: str
    flow: List[str] = Field(default_factory=list)


class StateItem(_OpenModel):
    """One piece of client-side React state in a screen."""
    name: str
    type: str                              # string | number | boolean | list | object | null


class ApiCall(_OpenModel):
    """One REST API call required by a screen."""
    name: str                              # camelCase function name, e.g. getProcesses
    method: str                            # GET | POST | PUT | DELETE
    endpoint: str = ""                    # REST path, e.g. /api/production-processes
    hook: str = "useApiRequest"


class DataFlow(_OpenModel):
    """Client-side state + API call catalogue for one screen."""
    state: List[StateItem] = Field(default_factory=list)
    api_calls: List[ApiCall] = Field(default_factory=list)


class ScreenPlan(_OpenModel):
    """Complete plan for one screen (dashboard, form, detail, popup)."""
    screen_name: str
    type: str                              # dashboard | form | detail | popup
    route: str = ""
    opens_as: str = "page"               # page | modal | popup
    priority: int = 1                     # build order within module (1 = first)
    similarity_query: str

    components: List[ComponentPlan] = Field(default_factory=list)
    user_interactions: List[UserInteraction] = Field(default_factory=list)
    data_flow: DataFlow = Field(default_factory=DataFlow)


# ─── Module level ─────────────────────────────────────────────────────────────

class SharedComponent(_OpenModel):
    """A component reused across multiple screens within the same module."""
    name: str
    toolkit_mapping: str = ""
    used_in_screens: List[str] = Field(default_factory=list)


class FilePlan(_OpenModel):
    """Plan for one source file in the module."""
    path: str                             # e.g. src/modules/ProductionProcess/pages/…tsx
    type: str                             # page | config | form | component | service | types | hook | …
    description: str
    belongs_to_screen: str = ""           # exact screen_name; "" for module-wide files
    uses_components: List[str] = Field(default_factory=list)
    toolkit_imports: Dict[str, List[str]] = Field(default_factory=dict)
    key_exports: List[str] = Field(default_factory=list)


class ModulePlan(_OpenModel):
    """Complete plan for one UI module."""
    module_name: str
    description: str
    priority: int = 1                     # build order across modules (1 = build first)
    similarity_query: str

    business_rules: List[str] = Field(default_factory=list)  # copied verbatim from extraction
    screens: List[ScreenPlan] = Field(default_factory=list)
    shared_components: List[SharedComponent] = Field(default_factory=list)
    file_structure: List[FilePlan] = Field(default_factory=list)


# ─── LLM usage ───────────────────────────────────────────────────────────────

class PlannerLLMUsage(BaseModel):
    """Token usage and cost for the Frontend Planner LLM calls."""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    input_cost_usd: float = 0.0
    output_cost_usd: float = 0.0
    total_cost_usd: float = 0.0
    model: str = ""

    model_config = ConfigDict(extra="ignore")


# ─── Top-level output ─────────────────────────────────────────────────────────

class PlannerOutput(BaseModel):
    """Internal top-level output of the Frontend Planner graph."""
    modules: List[ModulePlan]
    usage: PlannerLLMUsage = Field(default_factory=PlannerLLMUsage)

    def get_all_files(self) -> List[Tuple[str, FilePlan]]:
        """Returns [(module_name, FilePlan), …] for every file across all modules."""
        return [(m.module_name, f) for m in self.modules for f in m.file_structure]

    def get_similarity_queries(self) -> Dict[str, List[str]]:
        """Returns {module_name: [query, …]} collecting all three-level similarity queries."""
        result: Dict[str, List[str]] = {}
        for m in self.modules:
            queries: List[str] = []
            if m.similarity_query:
                queries.append(m.similarity_query)
            for screen in m.screens:
                if screen.similarity_query:
                    queries.append(screen.similarity_query)
                for comp in screen.components:
                    if comp.similarity_query:
                        queries.append(comp.similarity_query)
            result[m.module_name] = queries
        return result


# ─── API request / response ───────────────────────────────────────────────────

class PlanRequest(BaseModel):
    """
    Request body for POST /frontend-planner/plan.

    extraction_id:
        UUID of the saved RequirementExtraction row in the
        ``requirement_extractions`` table.  The mode stored in that row
        must be 'frontend' or 'both'.
    parallel:
        When True (default), runs one focused LLM call per module in
        parallel (better quality, same cost).  When False, falls back to
        a single LLM call for all modules.
    """
    extraction_id: str = Field(..., description="UUID of a saved requirement_extractions row (mode must be 'frontend' or 'both')")
    parallel: bool = Field(default=True, description="Run one LLM call per module in parallel (recommended)")


class PlanResponse(BaseModel):
    """
    HTTP 200 response for POST /frontend-planner/plan.

    Fields
    ------
    status       — always "success" on HTTP 200.
    plan_id      — UUID of the newly created frontend_plans row.
    extraction_id — echoed back from the request.
    modules      — list of per-module plans (screens → components → file manifest).
    usage        — aggregated LLM token / cost summary for all planning calls.
    """
    status: Literal["success"] = "success"
    plan_id: str
    extraction_id: str
    modules: List[ModulePlan]
    usage: PlannerLLMUsage

    model_config = ConfigDict(extra="ignore")
