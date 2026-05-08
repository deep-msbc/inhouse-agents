"""
Central API router.

All module routers are registered here and mounted onto the FastAPI app
via main.py with the API version prefix.
"""

from fastapi import APIRouter

from src.msbc.api.v1.endpoints.requirements import router as requirement_extractor_router
from src.msbc.api.v1.endpoints.frontend_planner import router as frontend_planner_router
from src.msbc.api.v1.endpoints.backend_generator import router as backend_generator_router
from src.msbc.api.v1.endpoints.code_generator import router as code_generator_router

api_router = APIRouter()

# ── Module routers ────────────────────────────────────────────────────────────
api_router.include_router(requirement_extractor_router)
api_router.include_router(frontend_planner_router)
api_router.include_router(backend_generator_router)
api_router.include_router(code_generator_router)
