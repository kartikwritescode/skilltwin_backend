import asyncio
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_goal_creation_and_async_generation(async_client: AsyncClient, auth_headers: dict):
    # 1. Create Goal with exact requested format
    payload = {
        "title": "Become a Principal Flutter Architect",
        "description": "Master declarative rendering, microtask scheduling, and enterprise state architectures",
        "deadline": "2026-12-31",
        "daily_minutes": 35,
        "current_level": "intermediate",
        "existing_knowledge": "Solid with Dart syntax and basic StatefulWidget lifecycle",
        "constraints": ["30-45 minutes per day", "Prefer text and code challenges"]
    }

    response = await async_client.post("/api/v1/goals", json=payload, headers=auth_headers)
    assert response.status_code == 201
    goal_data = response.json()

    assert goal_data["title"] == payload["title"]
    assert goal_data["description"] == payload["description"]
    assert goal_data["deadline"] == payload["deadline"]
    assert goal_data["daily_minutes"] == 35
    assert goal_data["current_level"] == "intermediate"
    assert goal_data["existing_knowledge"] == payload["existing_knowledge"]
    assert goal_data["constraints"] == payload["constraints"]
    assert goal_data["status"] == "active"
    assert goal_data["active_journey_id"] is not None

    # Immediate response state is PENDING or PROCESSING (non-blocking)
    assert goal_data["generation_status"] in ("PENDING", "PROCESSING", "READY")

    goal_id = goal_data["id"]
    journey_id = goal_data["active_journey_id"]

    # Yield control to allow background asyncio task to complete generation
    await asyncio.sleep(0.05)

    # 2. Check Journey state after background generation finishes
    journey_resp = await async_client.get(f"/api/v1/journeys/{journey_id}", headers=auth_headers)
    assert journey_resp.status_code == 200
    journey_data = journey_resp.json()
    assert journey_data["generation_status"] == "READY"
    assert len(journey_data["nodes"]) > 0


@pytest.mark.asyncio
async def test_list_and_get_goal(async_client: AsyncClient, auth_headers: dict):
    # List goals for user
    list_resp = await async_client.get("/api/v1/goals", headers=auth_headers)
    assert list_resp.status_code == 200
    goals = list_resp.json()
    assert isinstance(goals, list)
    assert len(goals) >= 1

    first_goal_id = goals[0]["id"]
    # Get specific goal
    get_resp = await async_client.get(f"/api/v1/goals/{first_goal_id}", headers=auth_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == first_goal_id


@pytest.mark.asyncio
async def test_patch_goal(async_client: AsyncClient, auth_headers: dict):
    # Create goal to patch
    create_resp = await async_client.post(
        "/api/v1/goals",
        json={
            "title": "Original Goal Title",
            "daily_minutes": 20,
            "deadline": "2026-06-30"
        },
        headers=auth_headers
    )
    goal_id = create_resp.json()["id"]

    # Patch goal
    patch_payload = {
        "title": "Updated Goal Title",
        "daily_minutes": 45,
        "deadline": "2026-10-15",
        "constraints": ["No weekend notifications"]
    }
    patch_resp = await async_client.patch(f"/api/v1/goals/{goal_id}", json=patch_payload, headers=auth_headers)
    assert patch_resp.status_code == 200
    updated = patch_resp.json()
    assert updated["title"] == "Updated Goal Title"
    assert updated["daily_minutes"] == 45
    assert updated["deadline"] == "2026-10-15"
    assert "No weekend notifications" in updated["constraints"]


@pytest.mark.asyncio
async def test_goal_isolation_between_users(
    async_client: AsyncClient, auth_headers: dict, secondary_auth_headers: dict
):
    # User 1 creates a goal
    create_resp = await async_client.post(
        "/api/v1/goals",
        json={"title": "Private User 1 Goal", "daily_minutes": 30},
        headers=auth_headers
    )
    goal_id = create_resp.json()["id"]

    # User 2 attempts to get User 1's goal -> Must be 401 Unauthorized
    unauthorized_get = await async_client.get(f"/api/v1/goals/{goal_id}", headers=secondary_auth_headers)
    assert unauthorized_get.status_code == 401
    assert unauthorized_get.json()["error"]["code"] == "UNAUTHORIZED"

    # User 2 attempts to patch User 1's goal -> Must be 401 Unauthorized
    unauthorized_patch = await async_client.patch(
        f"/api/v1/goals/{goal_id}",
        json={"title": "Hacked Title"},
        headers=secondary_auth_headers
    )
    assert unauthorized_patch.status_code == 401
    assert unauthorized_patch.json()["error"]["code"] == "UNAUTHORIZED"
