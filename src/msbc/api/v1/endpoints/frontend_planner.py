"""
Frontend Planner — FastAPI router (async job pattern).

POST /frontend-planner/plan
  Accepts an extraction_id (UUID of a saved RequirementExtraction row whose
  mode is 'frontend' or 'both'). Validates the extraction synchronously, creates
  a job record, and immediately returns a job_id (HTTP 202).
  The LangGraph planning workflow runs in the background.

GET /frontend-planner/jobs/{job_id}
  Poll the status of a previously submitted planning job.
  Returns "pending" | "processing" while the job is in flight, and the
  full per-module plan once completed.
"""

import logging
from contextlib import contextmanager

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.helpers.message import LLM_ERRORS
from src.msbc.database.base import engine
from src.msbc.database.repositories import FrontendPlanRepository, JobRepository, RequirementRepository
from src.msbc.database.session import get_db
from src.msbc.models.schemas.frontend_plan import PlanRequest
from src.msbc.models.schemas.job import JobStatusResponse, JobSubmitResponse
from src.msbc.orchestration.planner.graph import run_frontend_planning

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/frontend-planner",
    tags=["Frontend Planner"],
)

# Modes that carry frontend requirements — backend-only extractions are rejected.
_FRONTEND_MODES = {"frontend", "both"}


# ─── Background-task DB helper ───────────────────────────────────────────────

@contextmanager
def _bg_session():
    """
    Yield a standalone SQLAlchemy Session for use inside background tasks.

    Background tasks run outside FastAPI's request lifecycle so they cannot
    use the ``get_db`` dependency.  This context manager provides an
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

async def _run_planning_job(
    job_id: str,
    extraction_id: str,
    extracted_requirements: dict,
    dependency_graph: dict | None,
    parallel: bool,
) -> None:
    """
    Background coroutine that runs the Frontend Planner LangGraph workflow
    and persists the result.

    Transitions: pending → processing → completed | failed
    """
    with _bg_session() as db:
        job_repo = JobRepository(db)
        job_repo.mark_processing(job_id)

    try:
        planner_output = await run_frontend_planning(
            extraction_id=extraction_id,
            extracted_requirements=extracted_requirements,
            dependency_graph=dependency_graph,
            parallel=parallel,
        )
    except Exception as exc:
        logger.error(
            "Background planning job %s failed (extraction_id=%s): %s",
            job_id, extraction_id, exc,
        )
        with _bg_session() as db:
            job_repo = JobRepository(db)
            job_repo.mark_failed(
                job_id,
                error_message=LLM_ERRORS["extraction_failed"].format(
                    exc_type=type(exc).__name__, detail=str(exc)
                ),
            )
        return

    # Persist the plan record
    plan_id: str = ""
    try:
        with _bg_session() as db:
            plan_repo = FrontendPlanRepository(db)
            plan_record = plan_repo.save_plan(
                extraction_id=extraction_id,
                plan=[m.model_dump() for m in planner_output.modules],
                usage=planner_output.usage.model_dump(),
            )
            plan_id = str(plan_record.id)
            logger.info(
                "Background job %s: plan saved — plan_id=%s, extraction_id=%s, modules=%d.",
                job_id, plan_id, extraction_id, len(planner_output.modules),
            )
    except Exception as exc:
        logger.error(
            "Background job %s: failed to persist plan for extraction_id=%s: %s",
            job_id, extraction_id, exc,
        )
        # Non-fatal — still mark the job completed with the in-memory result

    # Mark job completed with the full result payload
    job_result = {
        "status": "success",
        "plan_id": plan_id,
        "extraction_id": extraction_id,
        "modules": [m.model_dump() for m in planner_output.modules],
        "usage": planner_output.usage.model_dump(),
    }
    with _bg_session() as db:
        job_repo = JobRepository(db)
        job_repo.mark_completed(job_id, result=job_result)

    logger.info(
        "Background job %s completed (plan_id=%s).", job_id, plan_id
    )


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post(
    "/plan",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a frontend planning job from extracted requirements",
    description=(
        "Accepts the UUID of a saved RequirementExtraction row (mode must be "
        "'frontend' or 'both'). Validates the extraction synchronously, then "
        "immediately returns a ``job_id`` (HTTP 202). The Frontend Planner "
        "LangGraph workflow — one focused LLM call per module in parallel — runs "
        "in the background. Poll ``GET /frontend-planner/jobs/{job_id}`` for "
        "status and the full per-module plan once completed."
    ),
    response_description="Job ID for polling",
    response_model=JobSubmitResponse,
)
async def plan_frontend(
    body: PlanRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> JobSubmitResponse:
    # ── Step 1: Load the source extraction row ────────────────────────────────
    req_repo = RequirementRepository(db)
    extraction = req_repo.get_by_run_id(body.extraction_id)

    if extraction is None:
        logger.warning(
            "plan_frontend: extraction_id=%s not found.", body.extraction_id
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No extraction found with id '{body.extraction_id}'.",
        )

    # ── Step 2: Validate extraction mode ─────────────────────────────────────
    if extraction.mode not in _FRONTEND_MODES:
        logger.warning(
            "plan_frontend: extraction_id=%s has mode='%s' — frontend planning "
            "requires mode 'frontend' or 'both'.",
            body.extraction_id, extraction.mode,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Extraction mode '{extraction.mode}' does not contain frontend "
                f"requirements. Re-run the extractor with mode 'frontend' or 'both'."
            ),
        )

    # ── Step 3: Create the job record ─────────────────────────────────────────
    job_repo = JobRepository(db)
    job = job_repo.create_job(job_type="frontend_planning")
    job_id = str(job.id)
    # Commit NOW so the row is visible to the background task's separate DB
    # session before FastAPI even sends the 202 response.
    db.commit()
    logger.info(
        "Created planning job %s for extraction_id='%s'.", job_id, body.extraction_id
    )

    # ── Step 4: Enqueue background LLM task ──────────────────────────────────
    background_tasks.add_task(
        _run_planning_job,
        job_id,
        str(extraction.id),
        extraction.extracted_requirements,
        extraction.dependency_graph,
        body.parallel,
    )

    return JobSubmitResponse(
        job_id=job_id,
        status="pending",
        message=(
            f"Planning job submitted. "
            f"Poll GET /frontend-planner/jobs/{job_id} for status and results."
        ),
    )


@router.get(
    "/jobs/{job_id}",
    summary="Poll the status of a frontend planning job",
    description=(
        "Returns the current lifecycle state of a previously submitted planning job. "
        "While the job is in flight the ``status`` field will be ``'pending'`` or "
        "``'processing'``.  Once complete the full per-module plan payload is "
        "included in the ``result`` field.  On failure ``error_message`` is populated."
    ),
    response_description="Job status and (when completed) full frontend plan result",
    response_model=JobStatusResponse,
)
def get_planning_job(
    job_id: str,
    db: Session = Depends(get_db),
) -> JobStatusResponse:
    job_repo = JobRepository(db)
    job = job_repo.get_by_job_id(job_id)

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No planning job found with id '{job_id}'.",
        )

    if job.job_type != "frontend_planning":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Job '{job_id}' is of type '{job.job_type}', "
                "not 'frontend_planning'. Use the correct jobs endpoint."
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
