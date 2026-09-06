from typing import List
from fastapi import APIRouter, Depends
from app.schemas.concepts import ConceptDetailResponse, MisconceptionSchema
from app.schemas.sessions import EvidenceSchema
from app.repositories.concept_repository import ConceptRepository, concept_repository
from app.repositories.learner_repository import LearnerRepository, learner_repository
from app.repositories.session_repository import SessionRepository, session_repository
from app.services.evidence_service import EvidenceService, evidence_service
from app.domain.learner.models import RetentionRisk, LearnerConceptStatus
from app.core.security import CurrentUser, get_current_user
from app.core.exceptions import EntityNotFoundError

router = APIRouter(prefix="/concepts", tags=["Concepts"])


@router.get("/{concept_id}", response_model=ConceptDetailResponse, summary="Get Concept Detail & Live Learner State")
async def get_concept_detail(
    concept_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    concept_repo: ConceptRepository = Depends(lambda: concept_repository),
    learner_repo: LearnerRepository = Depends(lambda: learner_repository),
    session_repo: SessionRepository = Depends(lambda: session_repository),
):
    """
    Returns concept curriculum definition together with the learner's live Twin state:
    - Multi-factor mastery score, confidence calibration, retention score, and risk score
    - Status, active misconceptions, evidence history, and next scheduled review
    """
    concept = await concept_repo.get_by_id(concept_id)
    if not concept:
        concept = await concept_repo.get_by_name_or_id(concept_id)
        if not concept:
            raise EntityNotFoundError("Concept", concept_id)

    # Fetch learner twin state
    state = await learner_repo.get_concept_state(current_user.user_id, concept.id)
    mastery_score = state.mastery_score if state else 0.0
    confidence_score = state.confidence_score if state else 0.0
    retention_score = state.retention_score if state else 100.0
    risk_score = state.risk_score if state else 0.0
    retention_risk = state.retention_risk if state else RetentionRisk.LOW
    concept_status = state.status if state else LearnerConceptStatus.NOT_STARTED
    evidence_count = state.evidence_count if state else 0
    last_seen_at = state.last_seen_at if state else None
    next_review_at = state.next_review_at if state else None

    # Fetch misconceptions and evidence
    misconceptions = await learner_repo.list_misconceptions_for_concept(current_user.user_id, concept.id)
    evidence_records = await session_repo.list_evidence_for_concept(current_user.user_id, concept.id)

    misc_schemas = [
        MisconceptionSchema(
            id=m.id,
            concept_id=m.concept_id,
            tag=m.tag,
            description=m.description,
            severity=m.severity,
            status=m.status,
            detected_at=m.detected_at,
        )
        for m in misconceptions
    ]

    evd_schemas = [
        EvidenceSchema(
            id=e.id,
            concept_id=e.concept_id,
            evidence_type=e.evidence_type,
            score=e.score,
            feedback=e.feedback,
            reasoning_score=e.reasoning_score,
            transfer_score=e.transfer_score,
            misconceptions_detected=e.misconceptions_detected,
            created_at=e.created_at,
        )
        for e in evidence_records
    ]

    mentor_rec = (
        f"Mastery at {mastery_score}%. Retention risk is {retention_risk.value}. "
        + ("Ready for active application practice." if mastery_score >= 70 else "Focus on core invariants.")
    )

    return ConceptDetailResponse(
        id=concept.id,
        name=concept.name,
        description=concept.description,
        domain=concept.domain,
        difficulty_level=concept.difficulty_level,
        prerequisites=concept.prerequisites,
        mastery=mastery_score,
        confidence=confidence_score,
        retention_risk=retention_risk,
        status=concept_status,
        evidence_count=evidence_count,
        mastery_score=mastery_score,
        confidence_score=confidence_score,
        retention_score=retention_score,
        risk_score=risk_score,
        last_seen_at=last_seen_at,
        next_review_at=next_review_at,
        last_evidence_at=last_seen_at,
        misconceptions=misc_schemas,
        evidence_history=evd_schemas,
        mentor_recommendation=mentor_rec,
    )


@router.get("/{concept_id}/evidence", response_model=List[EvidenceSchema], summary="Get Concept Evidence History")
async def get_concept_evidence(
    concept_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    evidence_svc: EvidenceService = Depends(lambda: evidence_service),
):
    """
    Returns the chronological history of empirical evidence proofs
    (recalls, practice problems, teach-backs, projects, delayed retrievals) for this concept.
    """
    records = await evidence_svc.list_evidence_for_concept(
        user_id=current_user.user_id, concept_id=concept_id
    )
    return [
        EvidenceSchema(
            id=e.id,
            concept_id=e.concept_id,
            evidence_type=e.evidence_type,
            score=e.score,
            feedback=e.feedback,
            reasoning_score=e.reasoning_score,
            transfer_score=e.transfer_score,
            misconceptions_detected=e.misconceptions_detected,
            created_at=e.created_at,
        )
        for e in records
    ]
