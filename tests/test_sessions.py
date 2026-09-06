import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_session_lifecycle(async_client: AsyncClient, auth_headers: dict):
    # 1. Start a practice session
    create_payload = {
        "concept_id": "concept_dart_async_and_streams",
        "session_type": "practice",
        "metadata": {"source": "today_recommendation"}
    }
    start_resp = await async_client.post("/api/v1/sessions", json=create_payload, headers=auth_headers)
    assert start_resp.status_code == 201
    start_data = start_resp.json()
    assert start_data["concept_id"] == "concept_dart_async_and_streams"
    assert start_data["status"] == "active"
    session_id = start_data["id"]

    # 2. Complete the session with proof of understanding
    complete_payload = {
        "user_submission": (
            "Streams provide asynchronous sequences of data. StreamController manages the sink and stream, "
            "and broadcasts allow multiple listeners without race conditions."
        ),
        "time_spent_seconds": 320,
        "self_reported_confidence": 85.0,
    }
    complete_resp = await async_client.post(
        f"/api/v1/sessions/{session_id}/complete",
        json=complete_payload,
        headers=auth_headers
    )
    assert complete_resp.status_code == 200
    complete_data = complete_resp.json()
    assert complete_data["status"] == "completed"
    assert complete_data["score"] is not None
    assert complete_data["score"] > 0
    assert len(complete_data["evidence"]) == 1

    evidence = complete_data["evidence"][0]
    assert evidence["concept_id"] == "concept_dart_async_and_streams"
    assert evidence["score"] > 0
    assert "feedback" in evidence
