"""
Pydantic schemas for the Backend Code Generation Pipeline (Stage 3).

Model responsibilities:
  CLIStrategy      — Resolves which djcli command to run given an extraction.
  CLIInvokerInput  — Typed input handed to the CLI invoker subprocess wrapper.
  CLIInvokerOutput — Result returned after djcli exits (success or failure).
  ValidationResult — Scaffold validator output: checks expected files exist.
  GeneratedFile    — Tracks one generated source file + its generation method.
  PipelineOutput   — Top-level result of the full Stage 3 pipeline run.

Locked invariants encoded in this contract:
  - use_api  is always True  — CLI flag --api is always passed explicitly.
  - use_auth is always False — CLI flag --auth is NEVER passed (locked decision).
  - Migration files are never generated; no field for them exists here.
  - urls.py and standard CRUD views are always generated via Jinja2.
  - models.py / serializers.py / custom views are always generated via LLM.

NOTE on enums:
  Framework and ExtractionMode are defined here for Stage 3 self-containment.
  If requirement.py (src/msbc/models/schemas/requirement.py) is confirmed to
  export these enums, replace the local definitions below with:
      from src.msbc.models.schemas.requirement import Framework, ExtractionMode
  Do NOT redefine them in both files — pick one home and import everywhere.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict


# ─── Enums ────────────────────────────────────────────────────────────────────

class Framework(str, Enum):
    """Target backend framework for code generation. Currently Django only."""
    DJANGO = "django"


class ExtractionMode(str, Enum):
    """Extraction mode from Stage 1 — determines which generation path runs."""
    FRONTEND   = "frontend"
    BACKEND    = "backend"
    FULL_STACK = "full_stack"


# ─── CLI planning ─────────────────────────────────────────────────────────────

class CLIStrategy(BaseModel):
    """
    Resolved djcli command strategy for a given extraction.

    Produced by the invoker before subprocess execution — allows dry-run
    inspection without actually running the CLI.
    """
    command: Literal["startproject", "startapp", "noop"]
    project_name: str
    app_names: List[str]
    existing_project_path: Optional[str] = None


# ─── CLI invocation ───────────────────────────────────────────────────────────

class CLIInvokerInput(BaseModel):
    """
    Typed input for the djcli subprocess wrapper.

    Built from ExtractionOutput (Stage 1 output) before invoking the CLI.
    app_names  — sanitised, unique Django app identifiers (snake_case).
    module_names — original module names before sanitisation (preserved for
                   display and traceability).

    LOCKED:
      use_api  = True  — --api flag is always passed to djcli.
      use_auth = False — --auth flag is NEVER passed (locked architecture decision).
    """
    project_name: str
    framework: Framework
    app_names: List[str]                                         # sanitized + unique
    module_names: List[str]                                      # originals pre-sanitization
    use_api: bool = True                                         # LOCKED — always True
    use_auth: bool = False                                       # LOCKED — never True
    command: Literal["startproject", "startapp", "noop"] = "startproject"
    existing_project_path: Optional[str] = None


# ─── CLI result ───────────────────────────────────────────────────────────────

class CLIInvokerOutput(BaseModel):
    """Result returned by the djcli subprocess wrapper after execution."""
    project_path: str
    framework: Framework
    generated_apps: List[str]
    skipped_apps: List[str] = []
    success: bool
    errors: List[str] = []


# ─── Scaffold validation ──────────────────────────────────────────────────────

class ValidationResult(BaseModel):
    """
    Output of the scaffold validator.

    Checks that djcli created the expected file tree before code generation
    starts. missing_files uses format "app_name/models.py" (relative paths).
    """
    success: bool
    project_path: str
    missing_files: List[str] = []                                # "app_name/models.py"
    errors: List[str] = []


# ─── Per-file tracking ────────────────────────────────────────────────────────

class GeneratedFile(BaseModel):
    """
    Tracks one generated source file and its generation metadata.

    generation_method:
      "llm"    — models.py, serializers.py, custom views.py
      "jinja2" — standard CRUD viewsets, urls.py (always Jinja2)

    syntax_valid is set to True only after ast.parse() passes (max 2 retries).
    """
    app_name: str
    file_type: Literal["models", "serializers", "views", "urls"]
    file_path: str                                               # absolute path on disk
    generation_method: Literal["llm", "jinja2"]
    syntax_valid: bool = False
    errors: List[str] = []


# ─── Pipeline top-level output ────────────────────────────────────────────────

class PipelineOutput(BaseModel):
    """
    Top-level result of the full Stage 3 backend code generation pipeline.

    Aggregates CLI invocation result + per-file generation results.
    success=True only when all apps were generated and all files passed
    ast.parse() syntax validation.
    """
    project_path: str
    framework: Framework
    generated_apps: List[str]
    generated_files: List[GeneratedFile] = []
    success: bool
    errors: List[str] = []

    model_config = ConfigDict(extra="ignore")

    # ── helpers ───────────────────────────────────────────────────────────────

    def get_files_by_type(
        self,
        file_type: Literal["models", "serializers", "views", "urls"],
    ) -> List[GeneratedFile]:
        """Return all generated files matching the given file_type."""
        return [f for f in self.generated_files if f.file_type == file_type]

    def get_files_by_app(self, app_name: str) -> List[GeneratedFile]:
        """Return all generated files belonging to the given app."""
        return [f for f in self.generated_files if f.app_name == app_name]