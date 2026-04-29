"""
Shared Pydantic schemas for the async Job pattern.

Both the Requirement Extractor and Frontend Planner endpoints use these
schemas to describe job submission and polling responses.

JobSubmitResponse  — returned immediately by POST endpoints
JobStatusResponse  — returned by GET /jobs/{job_id} endpoints
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class JobSubmitResponse(BaseModel):
    """
    Immediate HTTP 202 response after submitting an async job.

    Fields
    ------
    job_id   — UUID to use when polling the status endpoint.
    status   — always ``"pending"`` at submission time.
    message  — human-readable hint for the caller.
    """
    job_id: str
    status: str = "pending"
    message: str = "Job submitted. Poll the status endpoint with job_id."


class JobStatusResponse(BaseModel):
    """
    Response for GET /jobs/{job_id}.

    Fields
    ------
    job_id        — the job UUID.
    job_type      — ``"requirement_extraction"`` or ``"frontend_planning"``.
    status        — ``"pending"`` | ``"processing"`` | ``"completed"`` | ``"failed"``.
    result        — full result payload (present only when status = ``"completed"``).
    error_message — error description (present only when status = ``"failed"``).
    created_at    — ISO-8601 UTC timestamp of job creation.
    updated_at    — ISO-8601 UTC timestamp of last status change.
    """
    job_id: str
    job_type: str
    status: str
    result: Optional[Any] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    model_config = {"extra": "allow"}
