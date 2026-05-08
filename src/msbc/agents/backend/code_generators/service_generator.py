"""LLM-based Django service file generator for Stage 3 backend code generation."""

import json
import logging
from pathlib import Path

import yaml

from src.msbc.agents.backend.syntax_validator import validate_syntax
from src.msbc.config import PROMPT_MAX_TOKENS, TOTAL_INPUT_TOKEN_LIMIT
from src.msbc.llm.clients.openai_client import call_llm_with_schema, count_tokens
from src.msbc.models.schemas.backend_pipeline import GeneratedFile

logger = logging.getLogger(__name__)

_PROMPTS_DIR = (
    Path(__file__).parent.parent.parent.parent  # src/msbc/
    / "llm" / "prompts" / "templates" / "backend_agent"
)

_CODE_SCHEMA: dict = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"code": {"type": "string"}},
    "required": ["code"],
}

_TOKEN_BUDGET = TOTAL_INPUT_TOKEN_LIMIT - PROMPT_MAX_TOKENS


def _load_prompt(name: str) -> dict[str, str]:
    path = _PROMPTS_DIR / f"{name}.yaml"
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _fmt(template: str, **kwargs: str) -> str:
    result = template
    for key, value in kwargs.items():
        result = result.replace(f"{{{key}}}", value)
    return result


def _truncate(text: str) -> str:
    if count_tokens(text) > _TOKEN_BUDGET:
        return text[: _TOKEN_BUDGET * 4]
    return text


class ServiceGenerator:
    async def generate(
        self,
        app_name: str,
        service_name: str,
        feature_name: str,
        model_name: str,
        model_file: str,
        service_methods: list[str],
        entities: list[dict],
        business_rules: list[str],
        scaffold_app_path: str,
    ) -> GeneratedFile:
        services_dir = Path(scaffold_app_path) / "services"
        services_dir.mkdir(parents=True, exist_ok=True)
        file_path = services_dir / f"{feature_name}_service.py"

        prompt_data = _load_prompt("service")

        entities_json = _truncate(json.dumps(entities, indent=2))
        service_methods_json = json.dumps(service_methods, indent=2)
        business_rules_str = "\n".join(business_rules) if business_rules else "None"

        system = _fmt(prompt_data["system"], module_name=app_name)
        base_user = _fmt(
            prompt_data["user_template"],
            module_name=app_name,
            service_name=service_name,
            feature_name=feature_name,
            model_name=model_name,
            model_file=model_file,
            service_methods_json=service_methods_json,
            entities_json=entities_json,
            business_rules=business_rules_str,
        )

        last_error: str | None = None
        for attempt in range(3):
            user = base_user
            if attempt > 0 and last_error:
                user += (
                    f"\n\nPREVIOUS ATTEMPT HAD PYTHON SYNTAX ERROR: {last_error}\n"
                    "Fix all syntax errors. Return valid Python inside the 'code' field."
                )

            try:
                result, _ = await call_llm_with_schema(
                    system_prompt=system,
                    user_prompt=user,
                    schema=_CODE_SCHEMA,
                    schema_name=f"service:{app_name}",
                )
                code: str = result["code"]
            except Exception as exc:
                last_error = str(exc)
                logger.warning("service_generator: LLM failed (attempt %d): %s", attempt + 1, exc)
                continue

            is_valid, error = validate_syntax(code)
            if is_valid:
                file_path.write_text(code, encoding="utf-8")
                logger.info("service_generator: wrote %s", file_path)
                return GeneratedFile(
                    app_name=app_name,
                    file_type="service",
                    file_path=str(file_path),
                    generation_method="llm",
                    syntax_valid=True,
                )
            last_error = error
            logger.warning(
                "service_generator: syntax error '%s' attempt %d: %s",
                app_name, attempt + 1, error,
            )

        return GeneratedFile(
            app_name=app_name,
            file_type="service",
            file_path=str(file_path),
            generation_method="llm",
            syntax_valid=False,
            errors=[last_error or "service generation failed after 3 attempts"],
        )
