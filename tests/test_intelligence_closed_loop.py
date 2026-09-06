import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient
from app.core.security import create_access_token
from app.services.mentor_decision_pipeline import mentor_decision_pipeline
from app.domain.mentor.models import ActionType


@pytest.mark.asyncio
async def test_mentor_decision_pipeline_14_steps(async_client: AsyncClient, auth_headers: dict):
    resp = await async_client.get("/api/v1/mentor/today", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()

    # Step 14 check: structured response metadata
    assert data["pipeline_steps_executed"] == 14
    assert "deadline_pressure" in data
    assert data["deadline_pressure"] in ["low", "normal", "medium", "high"]

    # Candidate actions ranking check: all 8 candidate actions evaluated
    assert "candidate_rankings" in data
    action_types_evaluated = {c["action_type"] for c in data["candidate_rankings"]}
    expected_actions = {"LEARN", "REVISE", "PRACTICE", "PROVE", "TEACH", "REMEDIATE", "SKIP", "REFLECT"}
    assert expected_actions.issubset(action_types_evaluated)

    # Verify ranking sorting (highest score first)
    scores = [c["score"] for c in data["candidate_rankings"]]
    assert scores == sorted(scores, reverse=True)

    # Top action matches recommendation
    assert data["recommended_action"]["action_type"] == data["candidate_rankings"][0]["action_type"]


@pytest.mark.asyncio
async def test_deadline_pressure_evaluation(async_client: AsyncClient):
    user_id = "user_deadline_pressure_test"
    token = create_access_token(user_id=user_id, email="deadline@skilltwin.ai")
    headers = {"Authorization": f"Bearer {token}"}

    # Create goal with immediate tight deadline (tomorrow)
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
    goal_payload = {
        "title": "Urgent Production Readiness",
        "description": "Must master entire backend stack under tight deadline",
        "deadline": tomorrow,
        "daily_minutes": 15,
        "current_level": "intermediate",
        "existing_knowledge": "Basic programming",
        "constraints": ["urgent_production_deadline"],
    }
    g_resp = await async_client.post("/api/v1/goals", json=goal_payload, headers=headers)
    assert g_resp.status_code == 201
    g_data = g_resp.json()

    # Wait for journey generation so deadline pressure has nodes to evaluate
    journey_id = g_data["active_journey_id"]
    for _ in range(30):
        j_resp = await async_client.get(f"/api/v1/journeys/{journey_id}", headers=headers)
        if j_resp.status_code == 200 and j_resp.json().get("generation_status") == "READY":
            break
        await asyncio.sleep(0.05)

    mentor_resp = await async_client.get("/api/v1/mentor/today", headers=headers)
    assert mentor_resp.status_code == 200
    m_data = mentor_resp.json()
    assert m_data["deadline_pressure"] in ["high", "medium"]


@pytest.mark.asyncio
async def test_complete_intelligence_closed_loop(async_client: AsyncClient):
    """
    Verifies the complete closed loop of the SkillTwin intelligence engine:
    GOAL -> JOURNEY -> LEARNER STATE -> RECOMMENDATION -> SESSION -> EVIDENCE -> LEARNER UPDATE -> JOURNEY UPDATE -> NEW RECOMMENDATION
    """
    user_id = "loop_learner_closed_loop"
    token = create_access_token(user_id=user_id, email="loop@skilltwin.ai")
    headers = {"Authorization": f"Bearer {token}"}

    # --------------------------------------------------------------------------
    # 1. GOAL: Create target goal
    # --------------------------------------------------------------------------
    goal_payload = {
        "title": "Dart & Reactive Architecture Mastery",
        "description": "Master asynchronous streams, state management, and production Flutter architectures",
        "deadline": (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d"),
        "daily_minutes": 30,
        "current_level": "intermediate",
        "existing_knowledge": "OOP basics",
        "constraints": [],
    }
    goal_resp = await async_client.post("/api/v1/goals", json=goal_payload, headers=headers)
    assert goal_resp.status_code == 201
    goal_data = goal_resp.json()
    goal_id = goal_data["id"]

    # --------------------------------------------------------------------------
    # 2. JOURNEY: Retrieve generated roadmap
    # --------------------------------------------------------------------------
    journey_data = {}
    for _ in range(30):
        journey_resp = await async_client.get(f"/api/v1/journeys/{goal_data['active_journey_id']}", headers=headers)
        if journey_resp.status_code == 200:
            journey_data = journey_resp.json()
            if journey_data.get("generation_status") == "READY":
                break
        await asyncio.sleep(0.05)

    assert journey_resp.status_code == 200
    assert len(journey_data["nodes"]) > 0
    initial_node = journey_data["nodes"][0]
    initial_progress = journey_data["progress"]

    # --------------------------------------------------------------------------
    # 3. LEARNER STATE: Verify initial Twin state
    # --------------------------------------------------------------------------
    twin_resp = await async_client.get("/api/v1/twin", headers=headers)
    assert twin_resp.status_code == 200
    twin_data = twin_resp.json()
    assert twin_data["user_id"] == user_id

    # --------------------------------------------------------------------------
    # 4. RECOMMENDATION: MentorDecisionPipeline proposes first action
    # --------------------------------------------------------------------------
    rec_resp = await async_client.get("/api/v1/mentor/today", headers=headers)
    assert rec_resp.status_code == 200
    rec_data = rec_resp.json()
    first_action = rec_data["recommended_action"]
    assert first_action["action_type"] in ["LEARN", "PRACTICE", "REMEDIATE"]

    # --------------------------------------------------------------------------
    # 5. SESSION: Spawn adaptive session based on recommendation
    # --------------------------------------------------------------------------
    session_payload = {
        "concept_id": first_action["concept_id"] or initial_node["concept_id"],
        "session_type": first_action["action_type"],
    }
    session_resp = await async_client.post("/api/v1/sessions", json=session_payload, headers=headers)
    assert session_resp.status_code == 201
    session_data = session_resp.json()
    session_id = session_data["id"]
    assert len(session_data["steps"]) > 0

    # --------------------------------------------------------------------------
    # 6. EVIDENCE & COMPLETION: Complete session with verified recall proof
    # --------------------------------------------------------------------------
    comp_payload = {
        "user_submission": "StreamController manages asynchronous stream events with sink and stream separation.",
        "time_spent_seconds": 300,
        "self_reported_confidence": 92.0,
        "step_responses": [
            {"step_order": 1, "response": "Stream subscription listeners buffer events safely."},
        ],
    }
    comp_resp = await async_client.post(f"/api/v1/sessions/{session_id}/complete", json=comp_payload, headers=headers)
    assert comp_resp.status_code == 200
    comp_data = comp_resp.json()
    assert comp_data["status"] == "completed"
    assert len(comp_data["evidence"]) > 0

    # --------------------------------------------------------------------------
    # 7. LEARNER UPDATE: Verify updated mastery & confidence
    # --------------------------------------------------------------------------
    concept_id = session_payload["concept_id"]
    concept_resp = await async_client.get(f"/api/v1/concepts/{concept_id}", headers=headers)
    assert concept_resp.status_code == 200
    concept_state = concept_resp.json()
    assert concept_state["mastery_score"] > 0
    assert concept_state["evidence_count"] >= 1

    # --------------------------------------------------------------------------
    # 8. JOURNEY UPDATE: Verify progress advanced and milestone node updated
    # --------------------------------------------------------------------------
    updated_journey_resp = await async_client.get(f"/api/v1/journeys/{goal_data['active_journey_id']}", headers=headers)
    assert updated_journey_resp.status_code == 200
    updated_journey = updated_journey_resp.json()
    assert updated_journey["progress"] >= initial_progress

    # --------------------------------------------------------------------------
    # 9. NEW RECOMMENDATION: Pipeline evaluates updated cognitive state
    # --------------------------------------------------------------------------
    next_rec_resp = await async_client.get("/api/v1/mentor/today", headers=headers)
    assert next_rec_resp.status_code == 200
    next_rec_data = next_rec_resp.json()
    next_action = next_rec_data["recommended_action"]
    assert next_action is not None
    assert next_rec_data["pipeline_steps_executed"] == 14
