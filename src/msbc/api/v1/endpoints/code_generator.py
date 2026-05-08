"""
Code Generator — FastAPI router (async job pattern).

POST /code-generator/generate
  Accepts a frontend_plan_id + extraction_id + output_dir (and optional
  module_filter). Validates both records synchronously, creates a job
  record, and immediately returns a job_id (HTTP 202).
  The generation + validation workflow runs in a background coroutine.

GET /code-generator/jobs/{job_id}
  Poll the status of a previously submitted code-generation job.
  Returns "pending" | "processing" while in-flight, and the full
  CodeGeneratorOutput payload once completed.
"""

import logging
import uuid
from contextlib import contextmanager
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from src.msbc.agents.code_generator.generator import run_code_generation
from src.msbc.agents.code_generator.validator_agent import run_validation
from src.msbc.database.base import engine
from src.msbc.database.repositories import (
    FrontendPlanRepository,
    JobRepository,
    RequirementRepository,
)
from src.msbc.database.session import get_db
from src.msbc.embedding.graph_store import KuzuStore
from src.msbc.embedding.store import QdrantStore
from src.msbc.models.schemas.code_generator import CodeGeneratorOutput, GenerateRequest
from src.msbc.models.schemas.job import JobStatusResponse, JobSubmitResponse

logger = logging.getLogger(__name__)

# Lazy singletons — initialised on first request, not at import time.
# Kuzu only allows one writer connection; deferring open avoids startup
# failures when the DB file doesn't exist yet or is still being built.
_kuzu_store: KuzuStore | None = None
_qdrant_store: QdrantStore | None = None


def _get_kuzu_store() -> KuzuStore:
    global _kuzu_store
    if _kuzu_store is None:
        _kuzu_store = KuzuStore()
    return _kuzu_store


def _get_qdrant_store() -> QdrantStore:
    global _qdrant_store
    if _qdrant_store is None:
        _qdrant_store = QdrantStore()
    return _qdrant_store

router = APIRouter(
    prefix="/code-generator",
    tags=["Code Generator"],
)


# ─── Output directory safety ──────────────────────────────────────────────────

def _validate_output_dir(output_dir: str) -> str:
    """
    Resolve output_dir as a subdirectory inside CODEGEN_OUTPUT_ROOT.

    ``output_dir`` should be a plain folder name (e.g. "my_project").
    The full path is constructed as CODEGEN_OUTPUT_ROOT / output_dir and
    created on disk if it does not exist.
    Raises ValueError if the resolved path somehow escapes the allowed root
    (path-traversal guard).
    """
    root = Path(settings.CODEGEN_OUTPUT_ROOT).resolve()
    target = (root / output_dir).resolve()

    if not str(target).startswith(str(root)):
        raise ValueError(
            f"output_dir '{output_dir}' is not a valid folder name."
        )

    target.mkdir(parents=True, exist_ok=True)
    return str(target)


# ─── Background-task DB helper ───────────────────────────────────────────────

@contextmanager
def _bg_session():
    """
    Yield a standalone SQLAlchemy Session for use inside background tasks.

    Background tasks run outside FastAPI's request lifecycle so they cannot
    reuse the ``get_db`` dependency.  This context manager provides an
    equivalent transactional session.
    """
    with Session(engine) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


# ─── Background task ─────────────────────────────────────────────────────────

async def _run_codegen_job(
    job_id: str,
    body: GenerateRequest,
    plan_modules: list[dict],
    extraction_rules_index: dict[str, list[str]],
) -> None:
    """
    Background coroutine that runs code generation + validation and
    persists the result.

    Transitions: pending → processing → completed | failed
    """
    # Mark job as processing
    with _bg_session() as db:
        job_repo = JobRepository(db)
        job_repo.mark_processing(job_id)

    try:
        kuzu_store = _get_kuzu_store()
        qdrant_store = _get_qdrant_store()

        # Phase 3: Generate all frontend files
        output: CodeGeneratorOutput = await run_code_generation(
            request=body,
            plan_modules=plan_modules,
            extraction_rules_index=extraction_rules_index,
            kuzu_store=kuzu_store,
            qdrant_store=qdrant_store,
        )

        # Phase 4: Validate + auto-fix generated files
        validated_files = await run_validation(
            generated_files=[f.model_dump() for f in output.generated_files],
            plan_modules=plan_modules,
            output_dir=body.output_dir,
        )

        # Merge validation results back into GeneratedFile objects
        validated_map = {f["file_path"]: f for f in validated_files}
        merged_files = []
        for f in output.generated_files:
            v = validated_map.get(f.file_path, {})
            merged = f.model_copy(update={
                "validation_passed": v.get("validation_passed", False),
                "validation_errors": v.get("validation_errors", []),
            })
            merged_files.append(merged)

        passed = sum(1 for f in merged_files if f.validation_passed)
        final_output = output.model_copy(update={
            "generated_files": merged_files,
            "validation_summary": {
                "total": len(merged_files),
                "passed": passed,
                "failed": len(merged_files) - passed,
            },
        })

        with _bg_session() as db:
            job_repo = JobRepository(db)
            job_repo.mark_completed(job_id, result=final_output.model_dump())

        logger.info(
            "[codegen] job %s completed — files=%d passed=%d failed=%d.",
            job_id,
            len(merged_files),
            passed,
            len(merged_files) - passed,
        )

    except Exception as exc:
        logger.error(
            "[codegen] job %s failed: %s", job_id, exc, exc_info=True
        )
        with _bg_session() as db:
            job_repo = JobRepository(db)
            job_repo.mark_failed(job_id, error_message=str(exc))


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post(
    "/generate",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a code generation job from a frontend plan",
    description=(
        "Accepts the UUID of a saved FrontendPlan row and the UUID of its source "
        "RequirementExtraction. Validates both records synchronously, then "
        "immediately returns a ``job_id`` (HTTP 202). "
        "The code generation + validation workflow runs in the background. "
        "Poll ``GET /code-generator/jobs/{job_id}`` for status and results."
    ),
    response_description="Job ID for polling",
    response_model=JobSubmitResponse,
)
async def generate(
    body: GenerateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> JobSubmitResponse:
    # ── Step 1: Validate and sanitize output_dir ──────────────────────────────
    try:
        safe_dir = _validate_output_dir(body.output_dir)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    # ── Step 2: Load FrontendPlan ─────────────────────────────────────────────
    plan_repo = FrontendPlanRepository(db)
    plan_row = plan_repo.get_by_plan_id(body.frontend_plan_id)
    if plan_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No FrontendPlan found with id '{body.frontend_plan_id}'.",
        )

    plan_modules: list[dict] = plan_row.plan or []
    if not plan_modules:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"FrontendPlan '{body.frontend_plan_id}' has no modules to generate.",
        )

    # ── Step 3: Load RequirementExtraction ────────────────────────────────────
    req_repo = RequirementRepository(db)
    try:
        uuid.UUID(body.extraction_id)  # validate format only
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"extraction_id is not a valid UUID: '{body.extraction_id}'.",
        )

    extraction_row = req_repo.get_by_run_id(body.extraction_id)
    if extraction_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No RequirementExtraction found with id '{body.extraction_id}'.",
        )

    # ── Step 4: Build extraction rules index ──────────────────────────────────
    extraction_data: dict = extraction_row.extracted_requirements or {}
    rules_index: dict[str, list[str]] = {}
    for mod in extraction_data.get("modules", []):
        name = mod.get("name", "")
        rules = [r for r in mod.get("business_rules", []) if r]
        if name and rules:
            rules_index[name] = rules

    # ── Step 5: Create the job record ────────────────────────────────────────
    job_repo = JobRepository(db)
    job = job_repo.create_job(job_type="code_generation")
    job_id = str(job.id)
    # Commit NOW so the row is visible to the background task's separate DB
    # session before FastAPI sends the 202 response.
    db.commit()

    logger.info(
        "Created code-gen job %s — plan_id='%s', extraction_id='%s', output_dir='%s'.",
        job_id, body.frontend_plan_id, body.extraction_id, safe_dir,
    )

    # ── Step 6: Enqueue background task ──────────────────────────────────────
    safe_body = body.model_copy(update={"output_dir": safe_dir})

    background_tasks.add_task(
        _run_codegen_job,
        job_id,
        safe_body,
        plan_modules,
        rules_index,
    )

    return JobSubmitResponse(
        job_id=job_id,
        status="pending",
        message=(
            f"Code generation job submitted. "
            f"Poll GET /code-generator/jobs/{job_id} for status and results."
        ),
    )


@router.get(
    "/jobs/{job_id}",
    summary="Poll the status of a code generation job",
    description=(
        "Returns the current lifecycle state of a previously submitted code-generation job. "
        "While the job is in flight the ``status`` field will be ``'pending'`` or "
        "``'processing'``. Once complete the full ``CodeGeneratorOutput`` payload is "
        "included in the ``result`` field. On failure ``error_message`` is populated."
    ),
    response_description="Job status and (when completed) full code generation result",
    response_model=JobStatusResponse,
)
def get_codegen_job(
    job_id: str,
    db: Session = Depends(get_db),
) -> JobStatusResponse:
    job_repo = JobRepository(db)
    job = job_repo.get_by_job_id(job_id)

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No code generation job found with id '{job_id}'.",
        )

    if job.job_type != "code_generation":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Job '{job_id}' is of type '{job.job_type}', "
                "not 'code_generation'. Use the correct jobs endpoint."
            ),
        )

    return JobStatusResponse(
        job_id=str(job.id),
        job_type=job.job_type,
        status=job.status,
        result=job.result if job.status == "completed" else None,
        error_message=job.error_message if job.status == "failed" else None,
        created_at=str(job.created_at) if job.created_at else None,
        updated_at=str(job.updated_at) if job.updated_at else None,
    )
