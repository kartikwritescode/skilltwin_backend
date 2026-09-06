from datetime import datetime, timezone, timedelta
import pytest
from httpx import AsyncClient
from app.domain.learner.models import LearnerConceptState, LearnerConceptStatus
from app.domain.sessions.models import EvidenceRecord, EvidenceType
from app.services.mastery_engine import MasteryEngine, mastery_engine
from app.services.learner_service import LearnerService, learner_service
from app.services.evidence_service import EvidenceService, evidence_service
from app.repositories.learner_repository import learner_repository


# ------------------------------------------------------------------------------
# 1. MasteryEngine Algorithmic Tests
# ------------------------------------------------------------------------------

def test_mastery_engine_scoring_weights():
    engine = MasteryEngine()
    initial_state = LearnerConceptState(
        user_id="user_1",
        concept_id="concept_streams",
        mastery_score=0.0,
        evidence_count=0
    )

    # 1. Record an initial RECALL evidence proof (weight 0.8)
    recall_evidence = EvidenceRecord(
        id="ev_1",
        user_id="user_1",
        concept_id="concept_streams",
        session_id=None,
        evidence_type=EvidenceType.RECALL,
        score=80.0,
        feedback="Good recall",
    )
    score_recall = engine.update_mastery(initial_state, [], recall_evidence)
    assert score_recall > 0.0

    # 2. Record a high-cognitive-depth PROJECT evidence proof (weight 1.5)
    project_evidence = EvidenceRecord(
        id="ev_2",
        user_id="user_1",
        concept_id="concept_streams",
        session_id=None,
        evidence_type=EvidenceType.PROJECT,
        score=80.0,
        feedback="Production pipeline built",
    )
    score_project = engine.update_mastery(initial_state, [], project_evidence)
    # Project evidence must yield higher mastery contribution than basic recall
    assert score_project > score_recall


def test_mastery_engine_confidence_calibration():
    engine = MasteryEngine()

    # Overconfident learner: claims 95% confidence, but score is only 40%
    calibrated_conf = engine.update_confidence(
        existing_confidence=0.0,
        self_reported_confidence=95.0,
        evidence_score=40.0,
    )
    # Calibrated confidence should be pulled down towards measured reality
    assert calibrated_conf < 95.0
    assert calibrated_conf > 40.0


def test_mastery_engine_retention_decay():
    engine = MasteryEngine()
    now = datetime.now(timezone.utc)

    # Concept seen 10 days ago with only 1 prior evidence proof
    retention_10d = engine.update_retention(
        last_seen_at=now - timedelta(days=10),
        evidence_count=1,
        now=now,
    )
    assert retention_10d < 80.0  # Decayed significantly

    # Concept seen 10 days ago with 6 prior evidence proofs (higher memory stability)
    retention_10d_stable = engine.update_retention(
        last_seen_at=now - timedelta(days=10),
        evidence_count=6,
        now=now,
    )
    # Repetition must buffer against memory decay
    assert retention_10d_stable > retention_10d


def test_mastery_engine_risk_calculation():
    engine = MasteryEngine()
    # High risk: low retention (30%), low mastery (40%), 2 active misconceptions
    high_risk = engine.update_risk(mastery_score=40.0, retention_score=30.0, misconception_count=2)
    assert high_risk > 60.0

    # Low risk: high retention (95%), high mastery (90%), 0 misconceptions
    low_risk = engine.update_risk(mastery_score=90.0, retention_score=95.0, misconception_count=0)
    assert low_risk < 20.0


# ------------------------------------------------------------------------------
# 2. EvidenceService & LearnerService Integration Tests
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_record_evidence_and_state_update():
    user_id = "test_learner_evidence_01"
    concept_id = "concept_algorithms"

    # Record first evidence: EXPLANATION (Teach-back)
    evidence = await evidence_service.record_evidence(
        user_id=user_id,
        concept_id=concept_id,
        evidence_type=EvidenceType.TEACH_BACK,
        score=88.0,
        feedback="Clear explanation of time complexity invariants",
        self_confidence=80.0,
    )
    assert evidence.id.startswith("evd_")
    assert evidence.evidence_type == EvidenceType.TEACH_BACK

    # Verify LearnerConceptState was updated persistently
    state = await learner_repository.get_concept_state(user_id, concept_id)
    assert state is not None
    assert state.evidence_count == 1
    assert state.mastery_score > 0.0
    assert state.confidence_score > 0.0
    assert state.retention_score == 100.0  # Freshly reinforced
    assert state.status == LearnerConceptStatus.LEARNING


# ------------------------------------------------------------------------------
# 3. API Endpoints: GET /twin, GET /concepts/{id}, GET /concepts/{id}/evidence
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_learner_twin_endpoint(async_client: AsyncClient, auth_headers: dict):
    response = await async_client.get("/api/v1/twin", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()

    assert "overall_mastery" in data
    assert "concepts_tracked" in data
    assert "concepts_mastered" in data
    assert "high_retention_risk_count" in data
    assert "concepts" in data
    assert "weaknesses" in data
    assert "recent_evidence" in data


@pytest.mark.asyncio
async def test_get_concept_evidence_endpoint(async_client: AsyncClient, auth_headers: dict):
    # Record a proof first
    await evidence_service.record_evidence(
        user_id="default_learner_01",
        concept_id="concept_recursion",
        evidence_type=EvidenceType.DELAYED_RETRIEVAL,
        score=92.0,
        feedback="Strong recall after 7 days",
    )

    # Call GET /api/v1/concepts/{concept_id}/evidence
    response = await async_client.get("/api/v1/concepts/concept_recursion/evidence", headers=auth_headers)
    assert response.status_code == 200
    evidence_list = response.json()
    assert isinstance(evidence_list, list)
    assert len(evidence_list) >= 1

    first_proof = evidence_list[0]
    assert first_proof["concept_id"] == "concept_recursion"
    assert first_proof["evidence_type"] == "DELAYED_RETRIEVAL"
    assert first_proof["score"] == 92.0
