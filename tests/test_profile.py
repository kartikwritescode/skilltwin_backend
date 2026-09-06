import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_profile(async_client: AsyncClient, auth_headers: dict):
    response = await async_client.get("/api/v1/profile", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "default_learner_01"
    assert data["email"] == "default_learner_01@skilltwin.ai"
    assert "timezone" in data
    assert "preferences" in data


@pytest.mark.asyncio
async def test_update_profile(async_client: AsyncClient, auth_headers: dict):
    patch_payload = {
        "full_name": "Kartik Architect",
        "timezone": "Asia/Kolkata",
        "preferences": {"daily_target_minutes": 45}
    }
    response = await async_client.patch("/api/v1/profile", json=patch_payload, headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["full_name"] == "Kartik Architect"
    assert data["timezone"] == "Asia/Kolkata"
    assert data["preferences"]["daily_target_minutes"] == 45
