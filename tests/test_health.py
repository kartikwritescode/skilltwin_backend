import pytest
from httpx import AsyncClient
from app.core.config import settings


@pytest.mark.asyncio
async def test_root_health(async_client: AsyncClient):
    response = await async_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == settings.APP_NAME
    assert "dependencies" in data


@pytest.mark.asyncio
async def test_v1_health(async_client: AsyncClient):
    response = await async_client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "SkillTwin API v1"
    assert data["dependencies"]["ai_provider"] == settings.LLM_PROVIDER
