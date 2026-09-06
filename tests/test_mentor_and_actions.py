import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_mentor_today(async_client: AsyncClient, auth_headers: dict):
    response = await async_client.get("/api/v1/mentor/today", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "greeting" in data
    assert "mentor_note" in data
    assert "recommended_action" in data
    action = data["recommended_action"]
    assert "action_type" in action
    assert "title" in action
    assert "reason" in action
    assert "estimated_minutes" in action
    assert "quick_action_label" in action


@pytest.mark.asyncio
async def test_mentor_chat_message(async_client: AsyncClient, auth_headers: dict):
    payload = {
        "message": "Why should I prioritize recursion before trees?",
        "context": {"current_screen": "home"}
    }
    response = await async_client.post("/api/v1/mentor/message", json=payload, headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "mentor"
    assert len(data["content"]) > 0
    assert "suggested_actions" in data
