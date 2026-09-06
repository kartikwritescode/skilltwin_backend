from datetime import datetime, timezone, timedelta
import pytest
from httpx import AsyncClient
from app.core.security import create_access_token
from app.domain.learner.models import LearnerConceptState, LearnerConceptStatus
from app.repositories.learner_repository import learner_repository
from app.schemas.knowledge import MaintenanceAction


@pytest.mark.asyncio
async def test_get_knowledge_maintenance_unauthorized(async_client: AsyncClient):
    response = await async_client.get("/api/v1/knowledge/maintenance")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_knowledge_maintenance_overview_rules(async_client: AsyncClient):
    user_id = "test_km_user"
    token = create_access_token(user_id=user_id, email="km_test@skilltwin.ai")
    headers = {"Authorization": f"Bearer {token}"}
    now = datetime.now(timezone.utc)

    # Seed 1 concept with FIX (misconceptions)
    await learner_repository.save_concept_state(
        LearnerConceptState(
            user_id=user_id,
            concept_id="concept_recursion",
            mastery_score=60.0,
            confidence_score=50.0,
            retention_score=70.0,
            risk_score=30.0,
            status=LearnerConceptStatus.LEARNING,
            misconception_tags=["infinite_loop_without_base_case"],
            evidence_count=2,
            last_seen_at=now,
            next_review_at=now + timedelta(days=1),
        )
    )

    # Seed 1 concept with REVISE (decayed retention)
    await learner_repository.save_concept_state(
        LearnerConceptState(
            user_id=user_id,
            concept_id="concept_dart_async_and_streams",
            mastery_score=75.0,
            confidence_score=70.0,
            retention_score=30.0,
            risk_score=65.0,
            status=LearnerConceptStatus.NEEDS_REVIEW,
            misconception_tags=[],
            evidence_count=4,
            last_seen_at=now - timedelta(days=10),
            next_review_at=now - timedelta(hours=1),
        )
    )

    response = await async_client.get("/api/v1/knowledge/maintenance", headers=headers)
    assert response.status_code == 200
    data = response.json()

    assert data["user_id"] == user_id
    assert data["total_concepts"] > 0
    assert "breakdown" in data
    assert "items" in data

    # Verify FIX item
    fix_item = next((item for item in data["items"] if item["concept_id"] == "concept_recursion"), None)
    assert fix_item is not None
    assert fix_item["action"] == MaintenanceAction.FIX.value
    assert "infinite_loop_without_base_case" in fix_item["misconceptions"]
    assert fix_item["priority"] == 1

    # Verify REVISE item
    revise_item = next((item for item in data["items"] if item["concept_id"] == "concept_dart_async_and_streams"), None)
    assert revise_item is not None
    assert revise_item["action"] == MaintenanceAction.REVISE.value
    assert revise_item["priority"] == 2

    assert data["breakdown"]["FIX"] >= 1
    assert data["breakdown"]["REVISE"] >= 1


@pytest.mark.asyncio
async def test_generate_personalized_notes_and_caching(async_client: AsyncClient, auth_headers: dict):
    payload = {
        "concept_id": "concept_recursion",
        "force_regenerate": False,
    }

    # 1. First generation (cache miss)
    resp1 = await async_client.post("/api/v1/knowledge/notes/generate", json=payload, headers=auth_headers)
    assert resp1.status_code == 200
    data1 = resp1.json()

    assert data1["concept_id"] == "concept_recursion"
    assert data1["title"] != ""
    assert data1["summary"] != ""
    assert isinstance(data1["key_points"], list) and len(data1["key_points"]) > 0
    assert data1["your_weakness"] != ""
    assert data1["remember_this"] != ""
    assert data1["next_action"] != ""
    assert data1["cached"] is False

    # 2. Second generation with same state (cache hit)
    resp2 = await async_client.post("/api/v1/knowledge/notes/generate", json=payload, headers=auth_headers)
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["cached"] is True
    assert data2["title"] == data1["title"]

    # 3. Third generation with force_regenerate (bypasses cache)
    force_payload = {
        "concept_id": "concept_recursion",
        "force_regenerate": True,
    }
    resp3 = await async_client.post("/api/v1/knowledge/notes/generate", json=force_payload, headers=auth_headers)
    assert resp3.status_code == 200
    data3 = resp3.json()
    assert data3["cached"] is False


@pytest.mark.asyncio
async def test_generate_notes_nonexistent_concept(async_client: AsyncClient, auth_headers: dict):
    payload = {
        "concept_id": "concept_does_not_exist_404",
        "force_regenerate": False,
    }
    resp = await async_client.post("/api/v1/knowledge/notes/generate", json=payload, headers=auth_headers)
    assert resp.status_code == 404
