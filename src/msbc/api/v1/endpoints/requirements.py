"""
Requirement Extractor — FastAPI router (async job pattern).

POST /requirement-extractor/parse
  Upload a .docx or .pdf user story document and select an extraction mode
  (frontend | backend | both). Returns a job_id immediately (HTTP 202).
  The heavy LLM extraction runs in the background.

GET /requirement-extractor/jobs/{job_id}
  Poll the status of a previously submitted extraction job.
  Returns "pending" | "processing" while the job is in flight, and the
  full structured requirements JSON (plus dependency graph) once completed.
"""

import logging
from contextlib import contextmanager

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.helpers.message import FILE_ERRORS, LLM_ERRORS
from src.msbc.database.base import engine
from src.msbc.database.repositories import JobRepository, RequirementRepository
from src.msbc.database.session import get_db
from src.msbc.models.schemas.job import JobStatusResponse, JobSubmitResponse
from src.msbc.orchestration.graph import run_extraction
from src.msbc.utils.extractors import (
    extract_heading_hierarchy,
    extract_text_from_file,
)
from src.msbc.utils.validators import (
    validate_file_size,
    validate_mode,
    validate_uploaded_file,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/requirement-extractor",
    tags=["Requirement Extractor"],
)


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

async def _run_extraction_job(
    job_id: str,
    document_text: str,
    heading_hierarchy: dict,
    mode: str,
    filename: str,
) -> None:
    """
    Background coroutine that runs the LangGraph extraction and persists results.

    Transitions: pending → processing → completed | failed
    """
    with _bg_session() as db:
        job_repo = JobRepository(db)
        job_repo.mark_processing(job_id)

    try:
        result = await run_extraction(
            document_text=document_text,
            heading_hierarchy=heading_hierarchy,
            mode=mode,
        )
    except Exception as exc:
        logger.error(
            "Background extraction job %s failed (mode=%s): %s", job_id, mode, exc
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

    # Persist the extraction record
    extraction_id: str = ""
    try:
        with _bg_session() as db:
            req_repo = RequirementRepository(db)
            record = req_repo.save_extraction(
                user_story_id=filename or "unknown",
                mode=mode,
                extracted_requirements=result.get("extraction", {}),
                dependency_graph=result.get("graph"),
                usage=result.get("usage", {}),
            )
            extraction_id = str(record.id)
            logger.info(
                "Background job %s: saved extraction run id=%s for '%s'.",
                job_id, extraction_id, filename,
            )
    except Exception as exc:
        logger.error(
            "Background job %s: failed to persist extraction result: %s", job_id, exc
        )
        # Non-fatal — still mark the job completed with the in-memory result

    # Mark job completed with the full result payload
    job_result = {
        "status": "success",
        "mode": mode,
        "filename": filename,
        "extraction_id": extraction_id,
        "extraction": result.get("extraction", {}),
        "graph": result.get("graph", {}),
        "usage": result.get("usage", {}),
    }
    with _bg_session() as db:
        job_repo = JobRepository(db)
        job_repo.mark_completed(job_id, result=job_result)

    logger.info(
        "Background job %s completed (extraction_id=%s).", job_id, extraction_id
    )


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post(
    "/parse",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a user story for async requirement extraction",
    description=(
        "Upload a user story document (.docx or .pdf) and choose an extraction "
        "mode (frontend | backend | both). The endpoint validates the file and "
        "extracts raw text locally, then immediately returns a ``job_id`` (HTTP 202). "
        "The LLM extraction runs in the background — poll "
        "``GET /requirement-extractor/jobs/{job_id}`` for status and results."
    ),
    response_description="Job ID for polling",
    response_model=JobSubmitResponse,
)
async def parse_user_story(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="User story document (.docx or .pdf)"),
    mode: str = Form(
        default="both",
        description="Extraction mode: 'frontend', 'backend', or 'both'",
    ),
    db: Session = Depends(get_db),
) -> JobSubmitResponse:
    # ── Step 1: Validate inputs ───────────────────────────────────────────────
    validate_uploaded_file(file)
    validate_mode(mode)

    # ── Step 2: Read file bytes ───────────────────────────────────────────────
    try:
        file_bytes = await file.read()
    except Exception as exc:
        logger.error("Failed to read uploaded file '%s': %s", file.filename, exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=FILE_ERRORS["read_failed"].format(detail=str(exc)),
        )

    validate_file_size(file_bytes)

    # ── Step 3: Extract text (local, fast) ───────────────────────────────────
    try:
        document_text = extract_text_from_file(
            file_bytes=file_bytes,
            filename=file.filename,
            content_type=file.content_type or "",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except Exception as exc:
        logger.error("Text extraction failed for '%s': %s", file.filename, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=FILE_ERRORS["extraction_failed"].format(detail=str(exc)),
        )

    if not document_text or not document_text.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=FILE_ERRORS["extraction_empty"],
        )

    # ── Step 4: Extract heading hierarchy (local, fast) ──────────────────────
    heading_hierarchy = extract_heading_hierarchy(
        file_bytes=file_bytes,
        filename=file.filename,
        content_type=file.content_type or "",
    )

    # ── Step 5: Create the job record ─────────────────────────────────────────
    job_repo = JobRepository(db)
    job = job_repo.create_job(job_type="requirement_extraction")
    job_id = str(job.id)
    # Commit NOW so the row is visible to the background task's separate DB
    # session before FastAPI even sends the 202 response.
    db.commit()
    logger.info(
        "Created extraction job %s for file='%s' mode='%s'.", job_id, file.filename, mode
    )

    # ── Step 6: Enqueue background LLM task ──────────────────────────────────
    background_tasks.add_task(
        _run_extraction_job,
        job_id,
        document_text,
        heading_hierarchy,
        mode,
        file.filename or "",
    )

    return JobSubmitResponse(
        job_id=job_id,
        status="pending",
        message=(
            f"Extraction job submitted. "
            f"Poll GET /requirement-extractor/jobs/{job_id} for status and results."
        ),
    )


@router.get(
    "/jobs/{job_id}",
    summary="Poll the status of a requirement extraction job",
    description=(
        "Returns the current lifecycle state of a previously submitted extraction job. "
        "While the job is in flight the ``status`` field will be ``'pending'`` or "
        "``'processing'``.  Once complete the full structured requirements payload is "
        "included in the ``result`` field.  On failure ``error_message`` is populated."
    ),
    response_description="Job status and (when completed) full extraction result",
    response_model=JobStatusResponse,
)
def get_extraction_job(
    job_id: str,
    db: Session = Depends(get_db),
) -> JobStatusResponse:
    job_repo = JobRepository(db)
    job = job_repo.get_by_job_id(job_id)

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No extraction job found with id '{job_id}'.",
        )

    if job.job_type != "requirement_extraction":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Job '{job_id}' is of type '{job.job_type}', "
                "not 'requirement_extraction'. Use the correct jobs endpoint."
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
