from typing import Optional

from pydantic import BaseModel


class GenerateRequest(BaseModel):
    frontend_plan_id: str
    extraction_id: str
    output_dir: str
    module_filter: Optional[str] = None


class ScreenContext(BaseModel):
    screen_name: str
    module_name: str
    toolkit_files: list[dict]
    example_files: list[dict]
    component_graph: list[dict]
    business_rules: list[str]
    screen_plan: dict


class GeneratedFile(BaseModel):
    module_name: str
    screen_name: str
    file_path: str
    file_type: str
    content: str
    validation_passed: bool = False
    validation_errors: list[str] = []
    prompt_tokens: int = 0
    completion_tokens: int = 0


class CodeGeneratorOutput(BaseModel):
    frontend_plan_id: str
    output_dir: str
    generated_files: list[GeneratedFile]
    validation_summary: dict
    success: bool
    errors: list[str]
