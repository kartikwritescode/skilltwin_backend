import pytest
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient
from app.services.retention_engine import RetentionEngine, retention_engine
from app.repositories.revision_repository import revision_repository
from app.domain.revision.models import ReviewItem
from app.services.recommendation_service import recommendation_service
from app.domain.mentor.models import ActionType
from app.ai.orchestrator.context_builder import MentorContext


def test_retention_engine_interval_expansion_and_contraction():
    engine = RetentionEngine()

    # Step 1: Consecutive successful retrievals expand intervals
    int1 = engine.calculate_next_interval(current_interval=1, is_successful=True, consecutive_successes=1)
    assert int1 == 3

    int2 = engine.calculate_next_interval(current_interval=3, is_successful=True, consecutive_successes=2)
    assert int2 == 7

    int3 = engine.calculate_next_interval(current_interval=7, is_successful=True, consecutive_successes=3)
    assert int3 == 14

    int4 = engine.calculate_next_interval(current_interval=14, is_successful=True, consecutive_successes=4)
    assert int4 == 30

    # Step 2: Failed retrieval immediately contracts interval to 1 day
    failed_int = engine.calculate_next_interval(current_interval=30, is_successful=False)
    assert failed_int == 1


def test_retention_engine_priority_combines_factors():
    engine = RetentionEngine()
    now = datetime.now(timezone.utc)

    # Concept A: High risk, overdue, active goal, previous failure
    pri_a, is_high_a, _ = engine.calculate_priority(
        last_reviewed=now - timedelta(days=10),
        next_review=now - timedelta(days=2),
        retention_score=35.0,
        retention_risk="high",
        is_goal_relevant=True,
        concept_importance=1.2,
        failed_retrievals=2,
        now=now,
    )
    assert is_high_a is True
    assert pri_a >= 75.0

    # Concept B: Low risk, not overdue, fresh review
    pri_b, is_high_b, _ = engine.calculate_priority(
        last_reviewed=now - timedelta(hours=4),
        next_review=now + timedelta(days=5),
        retention_score=95.0,
        retention_risk="low",
        is_goal_relevant=False,
        concept_importance=1.0,
        failed_retrievals=0,
        now=now,
    )
    assert is_high_b is False
    assert pri_b < pri_a


@pytest.mark.asyncio
async def test_revision_next_endpoint_tracks_all_retention_fields(async_client: AsyncClient, auth_headers: dict):
    resp = await async_client.get("/api/v1/revision/next", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["primary_review_item"] is not None
    item = data["primary_review_item"]

    # Verify all tracked fields specified by prompt:
    # last_reviewed, next_review, interval, successful_retrievals, failed_retrievals, retention_score
    assert "last_reviewed" in item
    assert "next_review" in item
    assert "interval" in item
    assert "successful_retrievals" in item
    assert "failed_retrievals" in item
    assert "retention_score" in item
    assert "priority_score" in item
    assert "is_high_priority" in item

    # Verify queue sorting: primary item has higher or equal priority to upcoming items
    for up_item in data["upcoming_items"]:
        assert item["priority_score"] >= up_item["priority_score"]


@pytest.mark.asyncio
async def test_revision_complete_endpoint_success_and_failure_flow(async_client: AsyncClient, auth_headers: dict):
    now = datetime.now(timezone.utc)
    test_item = ReviewItem(
        id="rev_test_retention_complete",
        user_id="default_learner_01",
        concept_id="concept_recursion",
        concept_name="Recursion Test",
        next_review=now - timedelta(hours=1),
        interval=1,
        last_reviewed=now - timedelta(days=3),
        successful_retrievals=0,
        failed_retrievals=0,
        retention_score=45.0,
    )
    await revision_repository.save(test_item)

    # 1. Complete with success
    success_payload = {
        "is_successful": True,
        "confidence": 90.0,
        "time_spent_seconds": 120,
    }
    resp1 = await async_client.post(
        f"/api/v1/revision/{test_item.id}/complete",
        json=success_payload,
        headers=auth_headers,
    )
    assert resp1.status_code == 200
    res1 = resp1.json()

    assert res1["successful_retrievals"] == 1
    assert res1["interval"] == 3  # Expanded from 1 to 3
    assert res1["retention_score"] >= 90.0
    assert "Next review in 3 days." in res1["next_review_text"]

    # 2. Complete next with failure (contracts back to 1 day)
    fail_payload = {
        "is_successful": False,
        "confidence": 30.0,
        "time_spent_seconds": 60,
    }
    resp2 = await async_client.post(
        f"/api/v1/revision/{test_item.id}/complete",
        json=fail_payload,
        headers=auth_headers,
    )
    assert resp2.status_code == 200
    res2 = resp2.json()

    assert res2["failed_retrievals"] == 1
    assert res2["interval"] == 1  # Contracted back to 1
    assert res2["retention_risk"] == "high"
    assert "Next review in 1 day." in res2["next_review_text"]


def test_mentor_recommends_revise_on_high_priority_retention():
    # Context with high priority retention item
    ctx = MentorContext(
        user_id="learner_retention_test",
        goal_id="goal_active",
        goal_title="Full Stack Architecture",
        current_concept_id="concept_recursion",
        current_concept_mastery=70.0,
        due_retention_items=[
            {
                "concept_id": "concept_recursion",
                "concept_name": "Recursion",
                "retention_risk": "high",
                "priority_score": 85.0,
                "is_high_priority": True,
            }
        ],
    )

    intent, concept_id, rule = recommendation_service.evaluate_deterministic_rules(ctx)
    assert intent == ActionType.REVISE
    assert concept_id == "concept_recursion"
    assert rule == "HIGH_RETENTION_RISK"
