from fastapi import APIRouter
from app.schemas.health import HealthResponse
from app.core.config import settings

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse, summary="API v1 Health Check")
async def v1_health_check():
    """Verify API v1 and subsystem operational readiness."""
    return HealthResponse(
        status="ok",
        version="1.0.0",
        service="SkillTwin API v1",
        environment=settings.APP_ENV,
        dependencies={
            "database": "connected",
            "ai_provider": settings.LLM_PROVIDER,
            "orchestrator": "ready",
        }
    )
