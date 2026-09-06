import pytest
from httpx import AsyncClient
from app.core.security import create_access_token
from app.repositories.session_repository import session_repository
from app.repositories.learner_repository import learner_repository
from app.domain.sessions.models import EvidenceType


@pytest.mark.asyncio
async def test_teach_transcribe_unauthorized(async_client: AsyncClient):
    files = {"file": ("audio.wav", b"RIFF....WAVEfmt ....data....", "audio/wav")}
    resp = await async_client.post("/api/v1/teach/transcribe", files=files)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_teach_transcribe_audio_success(async_client: AsyncClient, auth_headers: dict):
    # Pass a valid audio payload with text cues
    sample_speech = (
        b"Recursion decomposes a problem into smaller identical instances until reaching "
        b"an invariant base condition where activation records unwind."
    )
    files = {"file": ("explanation.wav", sample_speech, "audio/wav")}
    data = {"concept_id": "concept_recursion"}

    resp = await async_client.post("/api/v1/teach/transcribe", files=files, data=data, headers=auth_headers)
    assert resp.status_code == 200
    res_data = resp.json()

    assert "transcript" in res_data
    assert len(res_data["transcript"]) > 0
    assert res_data["duration_seconds"] > 0
    assert res_data["word_count"] > 0
    assert res_data["confidence"] > 0.8
    assert res_data["detected_language"] == "en"


@pytest.mark.asyncio
async def test_teach_transcribe_empty_audio_fails(async_client: AsyncClient, auth_headers: dict):
    files = {"file": ("empty.wav", b"", "audio/wav")}
    resp = await async_client.post("/api/v1/teach/transcribe", files=files, headers=auth_headers)
    assert resp.status_code in [400, 422]


@pytest.mark.asyncio
async def test_teach_evaluate_structured_output_and_learner_update(async_client: AsyncClient):
    user_id = "teach_learner_01"
    token = create_access_token(user_id=user_id, email="teach01@skilltwin.ai")
    headers = {"Authorization": f"Bearer {token}"}

    explanation = (
        "Recursion is an algorithmic technique where a function calls itself with a strictly reduced subproblem. "
        "Each call pushes a new activation frame onto the call stack. The base case invariant is essential to "
        "terminate execution and allow the stack frames to pop and unwind backwards with the aggregated result."
    )

    payload = {
        "concept_id": "concept_recursion",
        "explanation_text": explanation,
        "audio_duration_seconds": 32.5,
        "self_reported_confidence": 85.0,
    }

    resp = await async_client.post("/api/v1/teach/evaluate", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    # Verify exact required schema
    assert data["concept_id"] == "concept_recursion"
    assert "conceptual_accuracy" in data
    assert "completeness" in data
    assert "reasoning" in data
    assert "confidence" in data
    assert "transfer" in data
    assert "misconceptions" in data
    assert "missing_concepts" in data
    assert "recommendation" in data
    assert isinstance(data["misconceptions"], list)
    assert isinstance(data["missing_concepts"], list)

    # Verify scores conform to ranges
    assert 0 <= data["conceptual_accuracy"] <= 100
    assert 0 <= data["completeness"] <= 100
    assert 0 <= data["reasoning"] <= 100
    assert 0 <= data["confidence"] <= 100
    assert 0 <= data["transfer"] <= 100

    # Verify Learner Model was updated through LearnerService
    assert data["evidence_id"] is not None
    assert data["updated_mastery_score"] > 0
    assert data["updated_confidence_score"] > 0
    assert data["updated_status"] in ["LEARNING", "MASTERED", "NEEDS_REVIEW", "NOT_STARTED"]

    # Verify persistent evidence record exists with TEACH_BACK type
    ev_records = await session_repository.list_evidence_for_concept(user_id, "concept_recursion")
    teach_ev = next((e for e in ev_records if e.id == data["evidence_id"]), None)
    assert teach_ev is not None
    assert teach_ev.evidence_type == EvidenceType.TEACH_BACK
    assert teach_ev.reasoning_score is not None


@pytest.mark.asyncio
async def test_teach_evaluate_detects_misconception_and_remediates(async_client: AsyncClient):
    user_id = "teach_learner_flawed"
    token = create_access_token(user_id=user_id, email="flawed@skilltwin.ai")
    headers = {"Authorization": f"Bearer {token}"}

    flawed_explanation = (
        "I wrote a recursive function but forgot the base case, causing an infinite loop and crash."
    )

    payload = {
        "concept_id": "concept_recursion",
        "explanation_text": flawed_explanation,
    }

    resp = await async_client.post("/api/v1/teach/evaluate", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["recommendation"] == "REMEDIATE"
    assert len(data["misconceptions"]) > 0
    assert "base_case_termination_flaw" in data["misconceptions"]

    # Verify learner model registered the misconception tag
    state = await learner_repository.get_concept_state(user_id, "concept_recursion")
    assert state is not None
    assert "base_case_termination_flaw" in state.misconception_tags


@pytest.mark.asyncio
async def test_teach_evaluate_nonexistent_concept(async_client: AsyncClient, auth_headers: dict):
    payload = {
        "concept_id": "concept_does_not_exist_404",
        "explanation_text": "This should fail because concept does not exist.",
    }
    resp = await async_client.post("/api/v1/teach/evaluate", json=payload, headers=auth_headers)
    assert resp.status_code == 404
