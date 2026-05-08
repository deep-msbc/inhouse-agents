"""
Backend Generator — FastAPI router (async job pattern).

POST /backend-generator/generate
  Submit extraction_id + output_path. Returns job_id immediately (HTTP 202).
  Heavy LangGraph pipeline runs in the background.

GET /backend-generator/jobs/{job_id}
  Poll the status of a previously submitted generation job.
"""

import logging
from contextlib import contextmanager

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.msbc.database.base import engine
from src.msbc.database.repositories import JobRepository, RequirementRepository
from src.msbc.database.repositories.backend_generation_repository import BackendGenerationRepository
from src.msbc.database.session import get_db
from src.msbc.models.entities.backend_generation import BackendGeneration
from src.msbc.models.schemas.job import JobStatusResponse, JobSubmitResponse
from src.msbc.orchestration.backend.graph import run_backend_codegen

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/backend-generator",
    tags=["Backend Generator"],
)


class BackendGenerateRequest(BaseModel):
    extraction_id: str
    output_path: str
    generation_mode: str = "startproject"   # "startproject" | "startapp" | "startservices"
    existing_project_name: str = ""         # required when generation_mode == "startapp"


# ─── Background-task DB helper ───────────────────────────────────────────────

@contextmanager
def _bg_session():
    """
    Standalone SQLAlchemy Session for background tasks.
    Background tasks run outside FastAPI's request lifecycle.
    """
    with Session(engine) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


# ─── Background task ─────────────────────────────────────────────────────────

async def _run_backend_job(
    job_id: str,
    extraction_id: str,
    output_path: str,
    generation_mode: str,
    existing_project_name: str,
) -> None:
    """Transitions: pending → processing → completed | failed."""
    with _bg_session() as db:
        JobRepository(db).mark_processing(job_id)

    # Load extraction record
    extracted_requirements: dict = {}
    dependency_graph = None
    try:
        with _bg_session() as db:
            record = RequirementRepository(db).get_by_id(extraction_id)
            if record is None:
                raise ValueError(f"No extraction found for id={extraction_id!r}")
            extracted_requirements = record.extracted_requirements or {}
            dependency_graph = record.dependency_graph
    except Exception as exc:
        logger.error("Backend job %s: failed to load extraction %s: %s", job_id, extraction_id, exc)
        with _bg_session() as db:
            JobRepository(db).mark_failed(job_id, error_message=str(exc))
        return

    # Run the pipeline
    try:
        pipeline_output = await run_backend_codegen(
            extraction_id=extraction_id,
            extracted_requirements=extracted_requirements,
            output_path=output_path,
            dependency_graph=dependency_graph,
            generation_mode=generation_mode,
            existing_project_name=existing_project_name,
        )
    except Exception as exc:
        logger.error("Backend job %s: pipeline failed: %s", job_id, exc)
        with _bg_session() as db:
            JobRepository(db).mark_failed(job_id, error_message=str(exc))
        return

    # Persist BackendGeneration record
    generation_id = ""
    try:
        with _bg_session() as db:
            record = BackendGeneration(
                extraction_id   = extraction_id,
                project_name    = pipeline_output.get("project_name", "") or "unknown",
                output_path     = output_path,
                pipeline_output = pipeline_output,
                success         = pipeline_output.get("success", False),
            )
            saved = BackendGenerationRepository(db).create(record)
            generation_id = str(saved.id)
    except Exception as exc:
        logger.error("Backend job %s: failed to persist generation record: %s", job_id, exc)

    job_result = {
        "status":          "success" if pipeline_output.get("success") else "completed_with_errors",
        "extraction_id":   extraction_id,
        "generation_id":   generation_id,
        "output_path":     output_path,
        "pipeline_output": pipeline_output,
    }

    with _bg_session() as db:
        JobRepository(db).mark_completed(job_id, result=job_result)

    logger.info("Backend job %s completed (generation_id=%s).", job_id, generation_id)


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post(
    "/generate",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a backend code generation job",
    description=(
        "Pass an extraction_id (from a completed requirement extraction) and an "
        "output_path (absolute directory where djcli will write the Django project). "
        "Returns a job_id immediately. Poll GET /backend-generator/jobs/{job_id} for status."
    ),
    response_model=JobSubmitResponse,
)
async def generate_backend(
    body: BackendGenerateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> JobSubmitResponse:
    job_repo = JobRepository(db)
    job      = job_repo.create_job(job_type="backend_generation")
    job_id   = str(job.id)
    # Commit before background task starts so the row is visible in its own session
    db.commit()

    logger.info(
        "Created backend generation job %s for extraction_id=%s output_path=%r",
        job_id, body.extraction_id, body.output_path,
    )

    background_tasks.add_task(
        _run_backend_job,
        job_id,
        body.extraction_id,
        body.output_path,
        body.generation_mode,
        body.existing_project_name,
    )

    return JobSubmitResponse(
        job_id=job_id,
        status="pending",
        message=(
            f"Backend generation job submitted. "
            f"Poll GET /backend-generator/jobs/{job_id} for status and results."
        ),
    )


@router.get(
    "/jobs/{job_id}",
    summary="Poll the status of a backend generation job",
    description=(
        "Returns the current lifecycle state of a previously submitted backend generation job. "
        "Status is 'pending' or 'processing' while in flight. "
        "Once complete the full pipeline_output is included in the result field."
    ),
    response_model=JobStatusResponse,
)
def get_backend_job(
    job_id: str,
    db: Session = Depends(get_db),
) -> JobStatusResponse:
    job = JobRepository(db).get_by_job_id(job_id)

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No backend generation job found with id '{job_id}'.",
        )

    if job.job_type != "backend_generation":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Job '{job_id}' is of type '{job.job_type}', "
                "not 'backend_generation'. Use the correct jobs endpoint."
            ),
        )

    return JobStatusResponse(
        job_id        = str(job.id),
        job_type      = job.job_type,
        status        = job.status,
        result        = job.result if job.status == "completed" else None,
        error_message = job.error_message if job.status == "failed" else None,
        created_at    = str(job.created_at) if job.created_at else None,
        updated_at    = str(job.updated_at) if job.updated_at else None,
    )
