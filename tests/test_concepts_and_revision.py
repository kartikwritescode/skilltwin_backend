import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_concept_detail(async_client: AsyncClient, auth_headers: dict):
    response = await async_client.get("/api/v1/concepts/concept_recursion", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "concept_recursion"
    assert "Recursion" in data["name"]
    assert "mastery" in data
    assert "retention_risk" in data
    assert "mentor_recommendation" in data


@pytest.mark.asyncio
async def test_revision_queue_and_submission(async_client: AsyncClient, auth_headers: dict):
    # 1. Get next revision
    rev_resp = await async_client.get("/api/v1/revision/next", headers=auth_headers)
    assert rev_resp.status_code == 200
    rev_data = rev_resp.json()
    assert "total_due_count" in rev_data
    assert rev_data["primary_review_item"] is not None

    item = rev_data["primary_review_item"]
    assert item["concept_id"] == "concept_recursion"
    assert item["retention_risk"] == "high"
    assert item["estimated_minutes"] == 4

    # 2. Submit retrieval result
    submit_payload = {
        "review_item_id": item["id"],
        "result": "good",
        "time_spent_seconds": 180,
    }
    submit_resp = await async_client.post("/api/v1/revision/submit", json=submit_payload, headers=auth_headers)
    assert submit_resp.status_code == 200
    updated_item = submit_resp.json()
    assert updated_item["repetitions"] == item["repetitions"] + 1
    assert updated_item["interval_days"] >= 1


@pytest.mark.asyncio
async def test_revision_experience_accuracy_confidence_and_notifications(async_client: AsyncClient, auth_headers: dict):
    # 1. Fetch queue
    rev_resp = await async_client.get("/api/v1/revision/next", headers=auth_headers)
    assert rev_resp.status_code == 200
    data = rev_resp.json()

    assert data["header"] == "5 minutes for your future self."
    assert data["primary_review_item"] is not None
    item = data["primary_review_item"]
    assert "why_today" in item and len(item["why_today"]) > 0
    assert "last_reviewed_at" in item
    assert "retention_risk" in item
    # Non-overwhelming queue check
    assert len(data["upcoming_items"]) <= 2

    # 2. Submit retrieval with accuracy + confidence (e.g. correct + confident)
    payload = {
        "review_item_id": item["id"],
        "accuracy": "correct",
        "confidence": "confident",
        "time_spent_seconds": 90,
    }
    sub_resp = await async_client.post("/api/v1/revision/submit", json=payload, headers=auth_headers)
    assert sub_resp.status_code == 200
    sub_data = sub_resp.json()
    assert "Next review in" in sub_data["next_review_text"]
    assert sub_data["interval"] >= 3
    assert sub_data["retention_risk"] == "low"

    # 3. Check mentor notifications UI endpoint
    notif_resp = await async_client.get("/api/v1/revision/notifications", headers=auth_headers)
    assert notif_resp.status_code == 200
    notif_data = notif_resp.json()
    assert "unread_count" in notif_data
    assert "notifications" in notif_data
