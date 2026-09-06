import pytest
from httpx import AsyncClient
from app.repositories.recommendation_repository import recommendation_repository
from app.domain.mentor.models import RecommendationRecord, ActionType


@pytest.mark.asyncio
async def test_adaptive_session_creation_with_recommendation(async_client: AsyncClient, auth_headers: dict):
    rec = RecommendationRecord(
        id="rec_test_remed_01",
        user_id="default_learner_01",
        goal_id="goal_test",
        concept_id="concept_recursion",
        action_type=ActionType.REMEDIATE,
        title="Fix Base Case Misconception",
        reason="Foundational recursion termination gap detected",
        estimated_minutes=15,
        confidence=0.95,
    )
    await recommendation_repository.save(rec)

    payload = {
        "recommendation_id": "rec_test_remed_01",
        "session_type": "REMEDIATE",
    }
    resp = await async_client.post("/api/v1/sessions", json=payload, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()

    assert data["session_type"].upper() == "REMEDIATE"
    assert data["recommendation_id"] == "rec_test_remed_01"
    assert len(data["steps"]) > 0

    step_types = [s["step_type"] for s in data["steps"]]
    assert any(st in ["DIAGNOSE", "EXPLAIN+", "PRACTICE", "APPLY", "TRANSFER", "TEACH", "RECALL"] for st in step_types)
    assert "DIAGNOSE" in step_types


@pytest.mark.asyncio
async def test_transactional_session_completion_pipeline(async_client: AsyncClient, auth_headers: dict):
    payload = {
        "concept_id": "concept_recursion",
        "session_type": "REMEDIATE",
    }
    create_resp = await async_client.post("/api/v1/sessions", json=payload, headers=auth_headers)
    assert create_resp.status_code == 201
    sess_id = create_resp.json()["id"]

    complete_payload = {
        "user_submission": "Termination guard invariant must prevent negative bounds and stack overflow.",
        "time_spent_seconds": 450,
        "self_reported_confidence": 88.0,
        "step_responses": [
            {"step_order": 1, "response": "Missing non-positive integer bound check."},
            {"step_order": 2, "response": "Frame pointer pops activation records in reverse order."}
        ]
    }
    comp_resp = await async_client.post(f"/api/v1/sessions/{sess_id}/complete", json=complete_payload, headers=auth_headers)
    assert comp_resp.status_code == 200
    comp_data = comp_resp.json()

    assert comp_data["status"] == "completed"
    assert comp_data["score"] >= 80.0
    assert len(comp_data["evidence"]) >= 1
    evidence = comp_data["evidence"][0]
    assert evidence["concept_id"] == "concept_recursion"
    assert evidence["reasoning_score"] is not None
    assert evidence["transfer_score"] is not None

    twin_resp = await async_client.get("/api/v1/twin", headers=auth_headers)
    assert twin_resp.status_code == 200
    twin_data = twin_resp.json()
    rec_concept = next((c for c in twin_data["concepts"] if c["concept_id"] == "concept_recursion"), None)
    assert rec_concept is not None
    assert rec_concept["mastery_score"] > 0
    assert rec_concept["retention_score"] == 100.0

    assert comp_data["next_recommendation"] is not None
