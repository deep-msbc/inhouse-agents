"""
Node implementations for the Backend Code Generation LangGraph workflow.

Phases:
  1  prepare_backend_node    — pure Python: parse extraction, build summaries
  2  backend_planner_node    — LLM: plan apps from module summaries
  3  cli_strategy_node       — pure Python: sanitize names, build CLIInvokerInput
  4  cli_invoker_node        — async subprocess: run djcli startproject
  5  scaffold_validator_node — pure Python: verify scaffold files exist
  6  codegen_app_node        — parallel via Send: generate code per app
  7  collect_apps_node       — pure Python: aggregate app_results
  8  project_settings_node   — pure Python: patch INSTALLED_APPS + project urls.py
  9  final_syntax_gate_node  — pure Python: ast.parse all generated files
  10 assemble_output_node    — pure Python: build final PipelineOutput dict
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import yaml

from src.msbc.agents.backend.cli_invoker import CLIInvoker
from src.msbc.agents.backend.code_generators.models_generator import ModelsGenerator
from src.msbc.agents.backend.code_generators.serializers_generator import SerializersGenerator
from src.msbc.agents.backend.code_generators.service_generator import ServiceGenerator
from src.msbc.agents.backend.code_generators.urls_generator import UrlsGenerator
from src.msbc.agents.backend.code_generators.views_generator import ViewsGenerator
from src.msbc.agents.backend.project_settings_updater import ProjectSettingsUpdater
from src.msbc.agents.backend.scaffold_validator import ScaffoldValidator
from src.msbc.agents.backend.syntax_validator import validate_syntax
from src.msbc.llm.clients.openai_client import call_llm_with_schema
from src.msbc.models.schemas.backend_pipeline import CLIInvokerInput, Framework
from src.msbc.orchestration.backend.state import AppCodegenResult, AppPlanSlice, BackendCodegenState

logger = logging.getLogger(__name__)

_PROMPTS_DIR = (
    Path(__file__).parent.parent.parent  # src/msbc/
    / "llm" / "prompts" / "templates" / "backend_agent"
)


def _load_prompt(name: str) -> dict[str, str]:
    path = _PROMPTS_DIR / f"{name}.yaml"
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _fmt(template: str, **kwargs: str) -> str:
    """str.replace substitution — JSON braces in YAML are safe."""
    result = template
    for key, value in kwargs.items():
        result = result.replace(f"{{{key}}}", value)
    return result


def _to_snake(name: str) -> str:
    name = re.sub(r"[^\w\s]", "", name)
    name = re.sub(r"\s+", "_", name.strip())
    return name.lower()


# ── JSON schema for backend_planner_node LLM output ──────────────────────────

_BACKEND_PLAN_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "project_name": {"type": "string"},
        "apps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "app_name":            {"type": "string"},
                    "module_name":         {"type": "string"},
                    "generation_order":    {"type": "integer"},
                    "endpoints":           {"type": "array", "items": {"type": "object"}},
                    "entities":            {"type": "array", "items": {"type": "object"}},
                    "relationships":       {"type": "array", "items": {"type": "object"}},
                    "business_logic":      {"type": "array", "items": {"type": "string"}},
                    "has_shared_enum_deps": {"type": "boolean"},
                    "services":            {"type": "array", "items": {"type": "object"}},
                    "lookup_fields":       {"type": "array", "items": {"type": "string"}},
                },
                "required": ["app_name", "module_name", "generation_order"],
            },
        },
    },
    "required": ["project_name", "apps"],
}


# ── Node 1: prepare_backend_node ──────────────────────────────────────────────

def prepare_backend_node(state: BackendCodegenState) -> dict[str, Any]:
    extraction: dict[str, Any] = state["extracted_requirements"]
    dep_graph: dict[str, Any] | None = state.get("dependency_graph")

    modules: list[dict[str, Any]] = extraction.get("modules", [])
    if not modules:
        logger.warning(
            "prepare_backend_node: no modules in extracted_requirements (extraction_id=%s)",
            state.get("extraction_id", "?"),
        )

    shared_enums: dict[str, Any] = extraction.get("global_enums", {})
    global_business_rules: list[str] = extraction.get("global_business_rules", [])

    dep_priority_map: dict[str, int] = {}
    if dep_graph:
        for node in dep_graph.get("nodes", []):
            name = node.get("name", "")
            priority = node.get("priority") or node.get("order") or 1
            if name:
                dep_priority_map[name] = int(priority)

    for idx, module in enumerate(modules):
        name = module.get("name", "")
        if name and name not in dep_priority_map:
            dep_priority_map[name] = idx + 1

    # Strip to summaries — BackendPlanner gets names + structure, not full detail
    module_summaries = [
        {
            "name": m.get("name", ""),
            "description": m.get("description", ""),
            "entities": [
                {"name": e.get("name", ""), "fields": e.get("fields", [])}
                for e in m.get("entities", [])
            ],
            "endpoints": [
                {
                    "path":      ep.get("path", ""),
                    "method":    ep.get("method", ""),
                    "operation": ep.get("operation", ""),
                }
                for ep in m.get("endpoints", [])
            ],
            "relationships":  m.get("relationships", []),
            "business_logic": m.get("business_logic", []),
        }
        for m in modules
    ]

    logger.info(
        "prepare_backend_node: %d module(s) ready (extraction_id=%s)",
        len(module_summaries), state.get("extraction_id", "?"),
    )

    return {
        "modules":               module_summaries,
        "shared_enums":          shared_enums,
        "global_business_rules": global_business_rules,
        "dep_priority_map":      dep_priority_map,
        "all_errors":            [],
        "app_results":           [],
    }


# ── Node 2: backend_planner_node ──────────────────────────────────────────────

async def backend_planner_node(state: BackendCodegenState) -> dict[str, Any]:
    modules              = state.get("modules", [])
    dep_priority_map     = state.get("dep_priority_map", {})
    shared_enums         = state.get("shared_enums", {})
    global_business_rules = state.get("global_business_rules", [])

    prompt_data = _load_prompt("backend_planner")

    system = prompt_data["system"]
    user = _fmt(
        prompt_data["user_template"],
        modules_json      = json.dumps(modules, indent=2),
        dep_priority_json = json.dumps(dep_priority_map, indent=2),
        shared_enums_json = json.dumps(shared_enums, indent=2),
        global_rules      = "\n".join(global_business_rules) if global_business_rules else "None",
    )

    result, _ = await call_llm_with_schema(
        system_prompt=system,
        user_prompt=user,
        schema=_BACKEND_PLAN_SCHEMA,
        schema_name="backend_plan",
    )

    logger.info(
        "backend_planner_node: planned %d app(s) (extraction_id=%s)",
        len(result.get("apps", [])), state.get("extraction_id", "?"),
    )

    return {"backend_plan": result}


# ── Node 3: cli_strategy_node ─────────────────────────────────────────────────

def cli_strategy_node(state: BackendCodegenState) -> dict[str, Any]:
    backend_plan = state.get("backend_plan", {})
    apps = backend_plan.get("apps", [])
    project_name = _to_snake(backend_plan.get("project_name", "")) or "generated_project"

    app_names: list[str] = []
    module_names: list[str] = []
    app_name_map: dict[str, str] = {}
    seen: set[str] = set()

    for app in apps:
        module_name = app.get("module_name", app.get("app_name", ""))
        sanitized   = _to_snake(app.get("app_name", module_name)) or _to_snake(module_name)
        if sanitized and sanitized not in seen:
            app_names.append(sanitized)
            module_names.append(module_name)
            app_name_map[module_name] = sanitized
            seen.add(sanitized)

    generation_mode       = state.get("generation_mode", "startproject")
    existing_project_name = state.get("existing_project_name", "")

    cli_strategy = {
        "command":               "startproject",
        "project_name":          project_name,
        "app_names":             app_names,
        "module_names":          module_names,
        "output_path":           state["output_path"],
        "app_name_map":          app_name_map,  # module_name → sanitized app_name
        "generation_mode":       generation_mode,
        "existing_project_name": existing_project_name,
    }

    logger.info("cli_strategy_node: project=%r apps=%r mode=%r", project_name, app_names, generation_mode)
    return {"cli_strategy": cli_strategy}


# ── Node 4: cli_invoker_node ──────────────────────────────────────────────────

async def cli_invoker_node(state: BackendCodegenState) -> dict[str, Any]:
    cli_strategy = state.get("cli_strategy", {})
    all_errors   = list(state.get("all_errors", []))

    cli_input = CLIInvokerInput(
        project_name          = cli_strategy["project_name"],
        framework             = Framework.DJANGO,
        app_names             = cli_strategy["app_names"],
        module_names          = cli_strategy["module_names"],
        output_path           = cli_strategy["output_path"],
        generation_mode       = cli_strategy.get("generation_mode", "startproject"),
        existing_project_name = cli_strategy.get("existing_project_name", ""),
    )

    result = await CLIInvoker().invoke(cli_input)

    cli_output: dict[str, Any] = result.output.model_dump()
    cli_output["stdout"] = result.stdout
    cli_output["stderr"] = result.stderr

    if not result.output.success:
        all_errors.extend(result.output.errors)
        logger.error("cli_invoker_node: djcli failed — %s", result.output.errors)

    return {"cli_output": cli_output, "all_errors": all_errors}


# ── Node 5: scaffold_validator_node ───────────────────────────────────────────

def scaffold_validator_node(state: BackendCodegenState) -> dict[str, Any]:
    cli_output   = state.get("cli_output", {})
    cli_strategy = state.get("cli_strategy", {})
    all_errors   = list(state.get("all_errors", []))

    project_path    = cli_output.get("project_path", "")
    project_name    = cli_strategy.get("project_name", "")
    app_names       = cli_strategy.get("app_names", [])
    generation_mode = state.get("generation_mode", "startproject")

    validation = ScaffoldValidator().validate(project_path, project_name, app_names, generation_mode=generation_mode)

    if not validation.success:
        all_errors.extend(validation.missing_files)
        all_errors.extend(validation.errors)
        logger.error(
            "scaffold_validator_node: %d missing file(s), %d error(s)",
            len(validation.missing_files), len(validation.errors),
        )

    return {"scaffold_valid": validation.success, "all_errors": all_errors}


# ── Conditional edge: scaffold → codegen fan-out ──────────────────────────────

def _route_scaffold_to_codegen(state: BackendCodegenState) -> list[Any]:
    from langgraph.graph import END
    from langgraph.types import Send

    if not state.get("scaffold_valid", False):
        return END

    backend_plan  = state.get("backend_plan", {})
    apps          = backend_plan.get("apps", [])
    cli_strategy  = state.get("cli_strategy", {})
    cli_output    = state.get("cli_output", {})
    project_path  = cli_output.get("project_path", "")
    project_name  = cli_strategy.get("project_name", "")
    shared_enums  = state.get("shared_enums", {})
    global_rules  = state.get("global_business_rules", [])
    app_name_map  = cli_strategy.get("app_name_map", {})

    sends: list[Send] = []
    for app in sorted(apps, key=lambda a: (a.get("generation_order") or 999, a.get("app_name", ""))):
        module_name        = app.get("module_name", "")
        sanitized_app_name = app_name_map.get(module_name, _to_snake(app.get("app_name", module_name)))

        slice_input: AppPlanSlice = {
            "app_plan":              {**app, "app_name": sanitized_app_name},
            "dep_priority":          app.get("generation_order", 1),
            "shared_enums":          shared_enums,
            "global_business_rules": global_rules,
            "project_path":          project_path,
            "project_name":          project_name,
            "generation_mode":       state.get("generation_mode", "startproject"),
        }
        sends.append(Send("codegen_app_node", slice_input))

    if not sends:
        return END

    logger.info("_route_scaffold_to_codegen: fanning out %d app(s)", len(sends))
    return sends


# ── Node 6: codegen_app_node (parallel via Send) ──────────────────────────────

async def codegen_app_node(slice_input: AppPlanSlice) -> dict[str, Any]:
    app_plan      = slice_input["app_plan"]
    app_name      = app_plan.get("app_name", "")
    project_path  = slice_input["project_path"]
    project_name  = slice_input["project_name"]
    shared_enums  = slice_input["shared_enums"]
    global_rules  = slice_input["global_business_rules"]

    generation_mode = slice_input.get("generation_mode", "startproject")
    if generation_mode == "startservices":
        # djcli startservices creates: output_path/svc_<app_name>/app/
        scaffold_app_path = str(Path(project_path) / f"svc_{app_name}" / "app")
    else:
        # startproject: output_path/<project_name>/<app_name>/  (project_path IS output_path/project_name)
        # startapp:     output_path/<project_name>/<app_name>/  (same structure)
        scaffold_app_path = str(Path(project_path) / app_name)
    entities       = app_plan.get("entities", [])
    relationships  = app_plan.get("relationships", [])
    endpoints      = app_plan.get("endpoints", [])
    business_logic = app_plan.get("business_logic", [])
    services_plan   = app_plan.get("services", [])
    lookup_fields   = app_plan.get("lookup_fields", [])
    primary_service = services_plan[0] if services_plan else {}
    service_name    = primary_service.get("name", f"{app_name.title().replace('_', '')}Service")
    feature_name    = app_name
    model_name      = f"{app_name.title().replace('_', '')}Model"
    model_file      = f"{app_name}_model"
    service_methods = primary_service.get("methods", ["list", "create", "update", "delete"])

    generated_files: list[dict] = []
    errors: list[str] = []

    # Step 1: models.py
    models_result = await ModelsGenerator().generate(
        app_name          = app_name,
        entities          = entities,
        relationships     = relationships,
        global_enums      = shared_enums,
        business_rules    = global_rules + business_logic,
        scaffold_app_path = scaffold_app_path,
    )
    generated_files.append(models_result.model_dump())
    if not models_result.syntax_valid:
        errors.extend(models_result.errors)

    # Step 1.5: services/<feature>_service.py
    service_result = await ServiceGenerator().generate(
        app_name=app_name,
        service_name=service_name,
        feature_name=feature_name,
        model_name=model_name,
        model_file=model_file,
        service_methods=service_methods,
        entities=entities,
        business_rules=global_rules + business_logic,
        scaffold_app_path=scaffold_app_path,
    )
    generated_files.append(service_result.model_dump())
    if not service_result.syntax_valid:
        errors.extend(service_result.errors)

    # Step 2: serializers.py (pipeline — needs models code)
    models_code = ""
    models_path = Path(models_result.file_path)
    if models_path.exists():
        models_code = models_path.read_text(encoding="utf-8")

    serializers_result = await SerializersGenerator().generate(
        app_name          = app_name,
        models_code       = models_code,
        endpoints         = endpoints,
        scaffold_app_path = scaffold_app_path,
        lookup_fields     = lookup_fields,
    )
    generated_files.append(serializers_result.model_dump())
    if not serializers_result.syntax_valid:
        errors.extend(serializers_result.errors)

    # Step 3: views.py (pipeline — needs serializers code)
    serializers_code = ""
    serializers_path = Path(serializers_result.file_path)
    if serializers_path.exists():
        serializers_code = serializers_path.read_text(encoding="utf-8")

    views_result = await ViewsGenerator().generate(
        app_name          = app_name,
        endpoints         = endpoints,
        serializers_code  = serializers_code,
        scaffold_app_path = scaffold_app_path,
        service_name      = service_name,
    )
    generated_files.append(views_result.model_dump())
    if not views_result.syntax_valid:
        errors.extend(views_result.errors)

    # Step 4: urls.py (pipeline — needs views code)
    views_code = ""
    views_path = Path(views_result.file_path)
    if views_path.exists():
        views_code = views_path.read_text(encoding="utf-8")

    urls_result = await UrlsGenerator().generate(
        app_name          = app_name,
        views_code        = views_code,
        scaffold_app_path = scaffold_app_path,
    )
    generated_files.append(urls_result.model_dump())
    if not urls_result.syntax_valid:
        errors.extend(urls_result.errors)

    success = len(errors) == 0
    logger.info(
        "codegen_app_node: app=%r done — success=%s errors=%d",
        app_name, success, len(errors),
    )

    app_result: AppCodegenResult = {
        "app_name":        app_name,
        "generated_files": generated_files,
        "errors":          errors,
        "success":         success,
    }
    return {"app_results": [app_result]}


# ── Node 7: collect_apps_node ─────────────────────────────────────────────────

def collect_apps_node(state: BackendCodegenState) -> dict[str, Any]:
    app_results = state.get("app_results", [])
    all_errors  = list(state.get("all_errors", []))
    all_files: list[dict] = []

    for result in app_results:
        all_files.extend(result.get("generated_files", []))
        all_errors.extend(result.get("errors", []))

    logger.info(
        "collect_apps_node: %d app(s), %d file(s), %d accumulated error(s)",
        len(app_results), len(all_files), len(all_errors),
    )
    return {"generated_files": all_files, "all_errors": all_errors}


# ── Node 8: project_settings_node ────────────────────────────────────────────

def project_settings_node(state: BackendCodegenState) -> dict[str, Any]:
    cli_output   = state.get("cli_output", {})
    backend_plan = state.get("backend_plan", {})
    cli_strategy = state.get("cli_strategy", {})
    all_errors   = list(state.get("all_errors", []))

    project_path = cli_output.get("project_path", "")
    project_name = backend_plan.get("project_name", "")
    app_names    = cli_strategy.get("app_names", [])

    if not project_path or not project_name:
        all_errors.append("project_settings_node: missing project_path or project_name")
        return {"all_errors": all_errors}

    updater = ProjectSettingsUpdater(project_path, project_name)
    for app_name in app_names:
        errs = updater.add_app(app_name)
        if errs:
            logger.warning("project_settings_node: add_app(%r) errors: %s", app_name, errs)
            all_errors.extend(errs)

    return {"all_errors": all_errors}


# ── Node 9: final_syntax_gate_node ────────────────────────────────────────────

def final_syntax_gate_node(state: BackendCodegenState) -> dict[str, Any]:
    generated_files = state.get("generated_files", [])
    all_errors      = list(state.get("all_errors", []))

    for file_dict in generated_files:
        if file_dict.get("syntax_valid"):
            continue
        file_path = file_dict.get("file_path", "")
        if not file_path:
            continue
        p = Path(file_path)
        if not p.exists():
            all_errors.append(f"final_syntax_gate: file not on disk: {file_path}")
            continue
        code = p.read_text(encoding="utf-8")
        is_valid, error = validate_syntax(code)
        if not is_valid:
            all_errors.append(f"{file_path}: {error}")

    return {"all_errors": all_errors}


# ── Node 10: assemble_output_node ─────────────────────────────────────────────

def assemble_output_node(state: BackendCodegenState) -> dict[str, Any]:
    all_errors      = state.get("all_errors", [])
    cli_output      = state.get("cli_output", {})
    backend_plan    = state.get("backend_plan", {})
    generated_files = state.get("generated_files", [])

    pipeline_output = {
        "project_name":    backend_plan.get("project_name", ""),
        "project_path":    cli_output.get("project_path", ""),
        "framework":       "django",
        "generated_apps":  cli_output.get("generated_apps", []),
        "generated_files": generated_files,
        "success":         len(all_errors) == 0,
        "errors":          all_errors,
    }

    logger.info(
        "assemble_output_node: success=%s apps=%d files=%d errors=%d",
        pipeline_output["success"],
        len(pipeline_output["generated_apps"]),
        len(generated_files),
        len(all_errors),
    )

    return {"pipeline_output": pipeline_output}
