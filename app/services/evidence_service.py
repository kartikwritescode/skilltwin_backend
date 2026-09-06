import uuid
from datetime import datetime, timezone
from typing import Optional, List
from app.domain.sessions.models import EvidenceRecord, EvidenceType
from app.repositories.session_repository import SessionRepository, session_repository
from app.core.logging import logger


class EvidenceService:
    """
    Manages the lifecycle of empirical evidence proofs (recalls, practice problems,
    teach-backs, projects, assessments, and delayed retrievals).
    """

    def __init__(self, session_repo: SessionRepository = session_repository):
        self.session_repo = session_repo

    async def record_evidence(
        self,
        user_id: str,
        concept_id: str,
        evidence_type: EvidenceType,
        score: float,
        feedback: str,
        session_id: Optional[str] = None,
        reasoning_score: Optional[float] = None,
        transfer_score: Optional[float] = None,
        misconceptions_detected: Optional[List[str]] = None,
        self_confidence: Optional[float] = None,
    ) -> EvidenceRecord:
        """
        Creates and persists an empirical evidence record, then notifies LearnerService
        to update live mastery, confidence, retention, and risk metrics.
        """
        evidence_id = f"evd_{uuid.uuid4().hex[:10]}"
        evidence = EvidenceRecord(
            id=evidence_id,
            user_id=user_id,
            concept_id=concept_id,
            session_id=session_id,
            evidence_type=evidence_type,
            score=max(0.0, min(100.0, score)),
            feedback=feedback,
            reasoning_score=reasoning_score,
            transfer_score=transfer_score,
            misconceptions_detected=misconceptions_detected or [],
            created_at=datetime.now(timezone.utc),
        )

        await self.session_repo.save_evidence(evidence)
        logger.info(f"Recorded evidence {evidence_id} ({evidence_type.value}, score: {score}) for concept {concept_id}")

        # Update Learner Twin state through LearnerService
        from app.services.learner_service import learner_service
        await learner_service.on_evidence_recorded(
            user_id=user_id,
            concept_id=concept_id,
            new_evidence=evidence,
            self_confidence=self_confidence,
        )

        return evidence

    async def list_evidence_for_concept(self, user_id: str, concept_id: str) -> List[EvidenceRecord]:
        """Returns chronological history of all verified proofs for a concept."""
        records = await self.session_repo.list_evidence_for_concept(user_id=user_id, concept_id=concept_id)
        records.sort(key=lambda e: e.created_at, reverse=True)
        return records


evidence_service = EvidenceService()
