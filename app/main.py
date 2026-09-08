from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import time

from app.core.config import settings
from app.core.logging import logger
from app.core.exceptions import SkillTwinException, domain_exception_handler
from app.api.v1.router import api_router
from app.schemas.health import HealthResponse


from app.core.database import init_db, check_db_health
from app.workers.retention_worker import retention_worker
import asyncio

_worker_task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup sequence
    logger.info(f"Starting {settings.APP_NAME} in '{settings.APP_ENV}' mode (Debug: {settings.DEBUG})")
    logger.info(f"Configured LLM Provider: {settings.LLM_PROVIDER} ({settings.LLM_MODEL})")
    await init_db()
    global _worker_task
    _worker_task = asyncio.create_task(retention_worker.start_periodic_worker(interval_seconds=3600))
    yield
    # Shutdown sequence
    logger.info("Gracefully shutting down SkillTwin Backend...")
    retention_worker.stop()
    if _worker_task and not _worker_task.done():
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass


def create_application() -> FastAPI:
    application = FastAPI(
        title="SkillTwin AI Mentor API",
        description=(
            "Contract and intelligence source-of-truth for the SkillTwin personalized AI mentor platform. "
            "Exposes adaptive goals, winding journey roadmaps, evidence-based learner twin state, "
            "real-time mentor guidance, and spaced retention retrieval practice."
        ),
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # CORS Middleware
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Structured request logging middleware
    @application.middleware("http")
    async def log_requests(request: Request, call_next):
        start_time = time.time()
        response = await call_next(request)
        duration_ms = round((time.time() - start_time) * 1000, 2)
        logger.info(
            f"{request.method} {request.url.path} -> {response.status_code} ({duration_ms}ms)"
        )
        return response

    # Exception Handlers
    application.add_exception_handler(SkillTwinException, domain_exception_handler)

    @application.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        err_str = str(exc).lower()
        if "429" in err_str or "quota" in err_str or "resource_exhausted" in err_str or "rate limit" in err_str:
            logger.warning(f"AI API quota exhausted: {exc}")
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "QUOTA_EXCEEDED",
                        "message": "AI API usage limit reached (quota exceeded). Please check your Gemini API key or try again later.",
                        "details": {"error": str(exc)},
                    }
                },
            )

        import traceback
        logger.error(f"Unhandled server error on {request.method} {request.url.path}: {exc}\n{traceback.format_exc()}")
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "Internal server error occurred.",
                    "details": {"error": str(exc) if settings.DEBUG else "Please contact support."},
                }
            },
        )

    # Root Health Check Endpoint
    @application.get("/health", response_model=HealthResponse, tags=["Health"], summary="Root Health Check")
    async def root_health():
        """Root health check for load balancers and container orchestrators."""
        db_alive = await check_db_health()
        return HealthResponse(
            status="ok" if db_alive else "degraded",
            version="1.0.0",
            service=settings.APP_NAME,
            environment=settings.APP_ENV,
            dependencies={
                "database": "connected" if db_alive else "disconnected",
                "ai_provider": settings.LLM_PROVIDER,
                "api_v1": "operational",
            }
        )

    # Mount API v1
    application.include_router(api_router, prefix=settings.API_V1_STR)

    return application


app = create_application()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
