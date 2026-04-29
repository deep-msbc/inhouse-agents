"""
DevAgents — Application Entry Point
"""

from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.middleware.cors import CORSMiddleware

from app.api.main_router import api_router
from app.core.config import settings
from app.core.logger import get_logger
from src.msbc.database.base import Base, engine
import src.msbc.models.entities  # noqa: F401 — registers ORM models with Base

logger = get_logger(__name__)


def _init_db() -> None:
    """Create all tables that don't exist yet (used for SQLite dev mode)."""
    if settings.DATABASE_URL.startswith("sqlite"):
        Base.metadata.create_all(bind=engine)
        logger.info("SQLite: tables created / verified via create_all")


def custom_generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}" if route.tags else route.name


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    debug=settings.DEBUG,
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
)

_init_db()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok", "project": settings.PROJECT_NAME, "version": settings.VERSION}


if __name__ == "__main__":
    import uvicorn

    logger.info("Starting %s on %s:%s", settings.PROJECT_NAME, settings.HOST, settings.PORT)
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.RELOAD,
    )
