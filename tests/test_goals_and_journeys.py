import asyncio
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_goal_and_get_journey(async_client: AsyncClient, auth_headers: dict):
    # 1. Create Goal
    payload = {
        "title": "Master Senior Flutter Architecture",
        "description": "State management, custom renders, and async pipelines",
        "deadline": "2026-12-31",
        "current_level": "intermediate",
        "daily_minutes": 45,
        "existing_knowledge": "Good Dart fundamentals",
        "constraints": ["No videos"]
    }
    response = await async_client.post("/api/v1/goals", json=payload, headers=auth_headers)
    assert response.status_code == 201
    goal_data = response.json()
    assert goal_data["title"] == payload["title"]
    assert goal_data["status"] == "active"
    assert goal_data["active_journey_id"] is not None

    goal_id = goal_data["id"]
    journey_id = goal_data["active_journey_id"]

    # 2. Get Goal Details
    goal_resp = await async_client.get(f"/api/v1/goals/{goal_id}", headers=auth_headers)
    assert goal_resp.status_code == 200
    assert goal_resp.json()["id"] == goal_id

    # Wait briefly for background async roadmap generation
    await asyncio.sleep(0.05)

    # 3. Get Journey Roadmap Details
    journey_resp = await async_client.get(f"/api/v1/journeys/{journey_id}", headers=auth_headers)
    assert journey_resp.status_code == 200
    journey_data = journey_resp.json()
    assert journey_data["id"] == journey_id
    assert journey_data["generation_status"] == "READY"
    assert len(journey_data["nodes"]) > 0

    # Verify signature winding roadmap layout coordinates
    first_node = journey_data["nodes"][0]
    assert first_node["order"] == 1
    assert first_node["state"] in ("CURRENT", "AVAILABLE")
    assert "position_x" in first_node
    assert "position_y" in first_node
    assert isinstance(first_node["position_x"], float)
    assert isinstance(first_node["position_y"], float)


@pytest.mark.asyncio
async def test_get_nonexistent_goal(async_client: AsyncClient, auth_headers: dict):
    response = await async_client.get("/api/v1/goals/nonexistent_goal_id", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ENTITY_NOT_FOUND"
