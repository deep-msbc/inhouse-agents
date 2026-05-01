# Phase 1: Stage 3 Foundation - Pattern Map

**Mapped:** 2026-04-29
**Files analyzed:** 5
**Analogs found:** 5 / 5

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `src/msbc/models/schemas/backend_pipeline.py` | schema (modify) | request-response | `src/msbc/models/schemas/backend_pipeline.py` itself | self — additive field only |
| `src/msbc/agents/backend/cli_invoker.py` | service / subprocess wrapper | request-response | `src/msbc/api/v1/endpoints/requirements.py` (background task pattern) + `app/utils/retry_utils.py` | role-match |
| `src/msbc/agents/backend/scaffold_validator.py` | utility / validator | transform | `src/msbc/agents/schemas/requirement_extractor/backend.py` structure; `ValidationResult` schema | role-match |
| `src/msbc/models/entities/backend_generation.py` | model / ORM entity | CRUD | `src/msbc/models/entities/frontend_plan.py` (FK entity, no updated_at) | exact |
| `src/msbc/database/repositories/backend_generation_repository.py` | repository | CRUD | `src/msbc/database/repositories/frontend_plan_repository.py` | exact |

---

## Pattern Assignments

### `src/msbc/models/schemas/backend_pipeline.py` (modify — add `output_path`)

**Change:** Add one field `output_path: str` to `CLIInvokerInput`. All other types are untouched.

**Analog:** The file itself (lines 66–87).

**Existing CLIInvokerInput** (lines 66–87 — copy this block, add `output_path` after `project_name`):
```python
class CLIInvokerInput(BaseModel):
    project_name: str
    framework: Framework
    app_names: List[str]
    module_names: List[str]
    use_api: bool = True
    use_auth: bool = False
    command: Literal["startproject", "startapp", "noop"] = "startproject"
    existing_project_path: Optional[str] = None
```

**After modification** — insert `output_path` as the second field:
```python
class CLIInvokerInput(BaseModel):
    project_name: str
    output_path: str                                              # D-01: caller-supplied target dir
    framework: Framework
    app_names: List[str]
    module_names: List[str]
    use_api: bool = True                                          # LOCKED
    use_auth: bool = False                                        # LOCKED
    command: Literal["startproject", "startapp", "noop"] = "startproject"
    existing_project_path: Optional[str] = None
```

---

### `src/msbc/agents/backend/cli_invoker.py` (create — subprocess wrapper service)

**Analog:** `src/msbc/api/v1/endpoints/requirements.py` (background task + session pattern), `app/utils/retry_utils.py` (not used in Phase 1 but importable).

**Imports pattern** — copy from `src/msbc/api/v1/endpoints/requirements.py` lines 16–36, adapted:
```python
from __future__ import annotations

import logging
import os
import subprocess

from src.msbc.models.schemas.backend_pipeline import CLIInvokerInput, CLIInvokerOutput

logger = logging.getLogger(__name__)
```

**Core subprocess pattern** — derived from CLAUDE.md §11. No analog exists yet; use this exact form:
```python
def invoke(self, input: CLIInvokerInput) -> CLIInvokerOutput:
    os.makedirs(input.output_path, exist_ok=True)          # D-02

    cmd = [
        "python", "-m", "djcli", input.command,
        input.project_name,
        *input.app_names,
        "--api",                                            # LOCKED: always present
        "--path", input.output_path,
        # NEVER --auth
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return CLIInvokerOutput(
            project_path=input.output_path,
            framework=input.framework,
            generated_apps=[],
            success=False,
            errors=["djcli timed out after 60s"],           # CLAUDE.md §6 exact text
        )
```

**Success/failure mapping pattern:**
```python
    success = result.returncode == 0
    errors = []
    if not success:
        errors.append(result.stderr.strip() or "djcli exited non-zero")

    return CLIInvokerOutput(
        project_path=os.path.join(input.output_path, input.project_name),
        framework=input.framework,
        generated_apps=input.app_names if success else [],
        success=success,
        errors=errors,
    )
```

**stdout/stderr capture** — `subprocess.run(..., capture_output=True, text=True)` gives `result.stdout` and `result.stderr` as plain strings. Pass both to `CLIInvokerOutput` for the ORM record.

---

### `src/msbc/agents/backend/scaffold_validator.py` (create — file-tree validator utility)

**Analog:** `ValidationResult` schema in `src/msbc/models/schemas/backend_pipeline.py` lines 103–113. No existing agent file validates a file tree; the pattern is derived from `ValidationResult`'s own shape.

**Imports pattern:**
```python
from __future__ import annotations

import logging
import os

from src.msbc.models.schemas.backend_pipeline import ValidationResult

logger = logging.getLogger(__name__)
```

**Core validation pattern** — expected files per CLAUDE.md §11 (5 files per app):
```python
_EXPECTED_FILES = ["__init__.py", "models.py", "serializers.py", "views.py", "urls.py"]

def validate(self, project_path: str, app_names: list[str]) -> ValidationResult:
    missing: list[str] = []
    errors: list[str] = []

    for app in app_names:
        for fname in _EXPECTED_FILES:
            full = os.path.join(project_path, app, fname)
            if not os.path.isfile(full):
                missing.append(f"{app}/{fname}")               # relative format per schema

    success = len(missing) == 0
    if not success:
        errors.append(f"djcli scaffold missing {len(missing)} expected file(s)")

    return ValidationResult(
        success=success,
        project_path=project_path,
        missing_files=missing,
        errors=errors,
    )
```

---

### `src/msbc/models/entities/backend_generation.py` (create — ORM entity)

**Analog:** `src/msbc/models/entities/frontend_plan.py` — exact match: has FK to `requirement_extractions.id`, `created_at` only (no `updated_at`), JSON payload column, `_uuid_col()` helper.

**Imports pattern** (lines 1–9 of `frontend_plan.py`, adapted):
```python
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from src.msbc.database.base import Base
```

**`_uuid_col()` helper** — copy verbatim from `frontend_plan.py` lines 27–31:
```python
def _uuid_col():
    """Return a UUID column type compatible with both PostgreSQL and SQLite."""
    if settings.DATABASE_URL.startswith("sqlite"):
        return String(36)
    from sqlalchemy.dialects.postgresql import UUID
    return UUID(as_uuid=True)
```

**Primary key pattern** — copy from `frontend_plan.py` lines 40–45:
```python
id: Mapped[str] = mapped_column(
    _uuid_col(),
    primary_key=True,
    default=lambda: str(uuid.uuid4()),
    comment="Unique backend generation run identifier",
)
```

**FK column pattern** — copy from `frontend_plan.py` lines 48–54 (the `extraction_id` column):
```python
extraction_id: Mapped[str] = mapped_column(
    String(36),
    ForeignKey("requirement_extractions.id", ondelete="CASCADE"),
    nullable=False,
    index=True,
    comment="FK → requirement_extractions.id — the source extraction this generation was derived from",
)
```

**Full column set for `BackendGeneration`** (D-03 exact spec, using patterns above):
```python
class BackendGeneration(Base):
    __tablename__ = "backend_generations"

    id: Mapped[str] = mapped_column(_uuid_col(), primary_key=True, default=lambda: str(uuid.uuid4()), comment="Unique run identifier")
    extraction_id: Mapped[str] = mapped_column(String(36), ForeignKey("requirement_extractions.id", ondelete="CASCADE"), nullable=False, index=True, comment="FK → requirement_extractions.id")
    project_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="snake_case djcli project name")
    output_path: Mapped[str] = mapped_column(String(1024), nullable=False, comment="Absolute disk path where Django project landed")
    cli_stdout: Mapped[str | None] = mapped_column(Text, nullable=True, comment="Raw djcli stdout — debug aid")
    cli_stderr: Mapped[str | None] = mapped_column(Text, nullable=True, comment="Raw djcli stderr — debug aid")
    pipeline_output: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="Full PipelineOutput.model_dump() — populated on success")
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, comment="True if pipeline completed without errors")
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), comment="UTC timestamp of row creation")

    def __repr__(self) -> str:
        return (
            f"<BackendGeneration id={self.id!s} "
            f"extraction_id={self.extraction_id!r} success={self.success!r}>"
        )
```

**`__repr__` style** — follows `frontend_plan.py` lines 78–82: `<ClassName field1=... field2=...>`.

---

### `src/msbc/database/repositories/backend_generation_repository.py` (create)

**Analog:** `src/msbc/database/repositories/frontend_plan_repository.py` — constructor pattern only.

Per D-05: only `create()` + `get_by_id()` needed — both inherited from `BaseRepository`. No list queries. No wrapper methods.

**DO NOT IMPLEMENT** the `create_generation()` and `get_by_generation_id()` methods shown in the analog. Those exist on `FrontendPlanRepository` but are explicitly excluded here by D-05. The class body is `__init__` only — callers construct a `BackendGeneration` instance directly and pass it to the inherited `repo.create()`.

**Imports pattern** (lines 1–9 of `frontend_plan_repository.py`, adapted):
```python
from __future__ import annotations

from sqlalchemy.orm import Session

from src.msbc.database.repositories.base_repository import BaseRepository
from src.msbc.models.entities.backend_generation import BackendGeneration
```

**Complete class** (D-05: callers use inherited create() and get_by_id() — no wrapper methods):
```python
class BackendGenerationRepository(BaseRepository[BackendGeneration]):

    def __init__(self, db: Session) -> None:
        super().__init__(BackendGeneration, db)
```

---

## Shared Patterns

### `_uuid_col()` Helper
**Source:** `src/msbc/models/entities/frontend_plan.py` lines 27–31 (also in `requirement_extraction.py` lines 29–35, `job.py` lines 32–37)
**Apply to:** `backend_generation.py`
**Note:** Each entity file defines its own local `_uuid_col()` — this is the established project pattern. Do NOT import it from another entity; redefine it in `backend_generation.py` verbatim.
```python
def _uuid_col():
    if settings.DATABASE_URL.startswith("sqlite"):
        return String(36)
    from sqlalchemy.dialects.postgresql import UUID
    return UUID(as_uuid=True)
```

### Background Task DB Session
**Source:** `src/msbc/api/v1/endpoints/requirements.py` lines 47–62 (`_bg_session` context manager)
**Apply to:** Future `src/msbc/api/v1/endpoints/backend_generator.py` (Phase 1 does not build the endpoint, but cli_invoker and scaffold_validator must be sync-safe for this pattern)
```python
@contextmanager
def _bg_session():
    with Session(engine) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
```

### Repository Constructor
**Source:** `src/msbc/database/repositories/frontend_plan_repository.py` lines 29–30
**Apply to:** `backend_generation_repository.py`
```python
def __init__(self, db: Session) -> None:
    super().__init__(BackendGeneration, db)
```

### BaseRepository.create() — flush + refresh
**Source:** `src/msbc/database/repositories/base_repository.py` lines 31–35
**Apply to:** All repository write methods — call `self.create(record)`, never call `self._db.add()` + `self._db.flush()` directly in a concrete repo method.
```python
def create(self, instance: T) -> T:
    self._db.add(instance)
    self._db.flush()
    self._db.refresh(instance)
    return instance
```

### `server_default=func.now()` for timestamps
**Source:** `src/msbc/models/entities/requirement_extraction.py` lines 87–92
**Apply to:** `backend_generation.py` `created_at` column — use `server_default=func.now()` not `default=datetime.utcnow`.
```python
created_at: Mapped[str] = mapped_column(
    DateTime(timezone=True),
    nullable=False,
    server_default=func.now(),
    comment="UTC timestamp of row creation",
)
```

---

## `src/msbc/models/entities/__init__.py` — Required Edit

After creating `backend_generation.py`, add the import to `__init__.py` so Alembic's `env.py` discovers the new table via `import src.msbc.models.entities`.

**Current file** (`src/msbc/models/entities/__init__.py` lines 1–7):
```python
"""ORM entity models (SQLAlchemy mapped classes)."""

from src.msbc.models.entities.requirement_extraction import RequirementExtraction
from src.msbc.models.entities.frontend_plan import FrontendPlan
from src.msbc.models.entities.job import Job

__all__ = ["RequirementExtraction", "FrontendPlan", "Job"]
```

**After edit** — add one import line and extend `__all__`:
```python
from src.msbc.models.entities.backend_generation import BackendGeneration

__all__ = ["RequirementExtraction", "FrontendPlan", "Job", "BackendGeneration"]
```

---

## No Analog Found

All 5 files have close analogs. No entries in this section.

---

## Metadata

**Analog search scope:** `src/msbc/models/entities/`, `src/msbc/database/repositories/`, `src/msbc/models/schemas/`, `src/msbc/agents/`, `src/msbc/api/v1/endpoints/`, `app/utils/`
**Files scanned:** 12
**Pattern extraction date:** 2026-04-29
