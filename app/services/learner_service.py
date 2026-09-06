import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from app.repositories.learner_repository import LearnerRepository, learner_repository
from app.repositories.concept_repository import ConceptRepository, concept_repository
from app.repositories.session_repository import SessionRepository, session_repository
from app.domain.learner.models import (
    LearnerConceptState,
    RetentionRisk,
    LearnerConceptStatus,
    Misconception,
    MisconceptionSeverity,
    LearnerTwinOverview,
)
from app.domain.sessions.models import EvidenceRecord, EvidenceType
from app.schemas.learner import LearnerTwinResponse, ConceptMasterySummary, WeaknessItem
from app.schemas.sessions import EvidenceSchema
from app.services.mastery_engine import MasteryEngine, mastery_engine
from app.ai.schemas.ai_schemas import EvaluationResult
from app.core.logging import logger


class LearnerService:
    """
    Manages the persistent Learner Model (Learner Twin).
    Orchestrates mastery calculation, confidence calibration, retention decay,
    and risk mitigation across concept nodes.
    """

    def __init__(
        self,
        repo: LearnerRepository = learner_repository,
        concept_repo: ConceptRepository = concept_repository,
        session_repo: SessionRepository = session_repository,
        engine: MasteryEngine = mastery_engine,
    ):
        self.repo = repo
        self.concept_repo = concept_repo
        self.session_repo = session_repo
        self.engine = engine

    async def get_or_create_concept_state(self, user_id: str, concept_id: str) -> LearnerConceptState:
        state = await self.repo.get_concept_state(user_id, concept_id)
        if not state:
            state = LearnerConceptState(
                user_id=user_id,
                concept_id=concept_id,
                mastery_score=0.0,
                confidence_score=0.0,
                retention_score=100.0,
                risk_score=0.0,
                status=LearnerConceptStatus.NOT_STARTED,
                evidence_count=0,
            )
            await self.repo.save_concept_state(state)
        return state

    # --------------------------------------------------------------------------
    # Explicit Update Functions Required by Spec
    # --------------------------------------------------------------------------

    def update_mastery(
        self,
        existing_state: LearnerConceptState,
        evidence_history: List[EvidenceRecord],
        new_evidence: EvidenceRecord,
    ) -> float:
        """Calculates updated mastery score based on correctness, application, and explanation."""
        return self.engine.update_mastery(existing_state, evidence_history, new_evidence)

    def update_confidence(
        self,
        existing_confidence: float,
        self_reported_confidence: Optional[float],
        evidence_score: float,
    ) -> float:
        """Calibrates subjective confidence against objective evidence."""
        return self.engine.update_confidence(existing_confidence, self_reported_confidence, evidence_score)

    def update_retention(
        self,
        last_seen_at: Optional[datetime],
        evidence_count: int,
        now: Optional[datetime] = None,
    ) -> float:
        """Calculates memory retention decay."""
        return self.engine.update_retention(last_seen_at, evidence_count, now)

    def update_risk(
        self,
        mastery_score: float,
        retention_score: float,
        misconception_count: int,
    ) -> float:
        """Calculates composite risk score."""
        return self.engine.update_risk(mastery_score, retention_score, misconception_count)

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
        """Direct entrypoint for recording evidence proofs and updating the learner model."""
        from app.services.evidence_service import evidence_service
        return await evidence_service.record_evidence(
            user_id=user_id,
            concept_id=concept_id,
            evidence_type=evidence_type,
            score=score,
            feedback=feedback,
            session_id=session_id,
            reasoning_score=reasoning_score,
            transfer_score=transfer_score,
            misconceptions_detected=misconceptions_detected,
            self_confidence=self_confidence,
        )

    async def on_evidence_recorded(
        self,
        user_id: str,
        concept_id: str,
        new_evidence: EvidenceRecord,
        self_confidence: Optional[float] = None,
    ) -> LearnerConceptState:
        """Invoked when an evidence proof is recorded to recalibrate the Learner Twin."""
        state = await self.get_or_create_concept_state(user_id, concept_id)
        evidence_history = await self.session_repo.list_evidence_for_concept(user_id, concept_id)

        now = datetime.now(timezone.utc)
        state.evidence_count += 1
        state.last_seen_at = now

        # 1. Update Mastery Score
        state.mastery_score = self.update_mastery(state, evidence_history, new_evidence)

        # 2. Update Confidence Score
        state.confidence_score = self.update_confidence(state.confidence_score, self_confidence, new_evidence.score)

        # 3. Update Retention Score (reset/reinforced by fresh evidence)
        state.retention_score = 100.0

        # 4. Record Misconceptions
        for tag in new_evidence.misconceptions_detected:
            if tag not in state.misconception_tags:
                state.misconception_tags.append(tag)
            misc = Misconception(
                id=f"misc_{uuid.uuid4().hex[:8]}",
                user_id=user_id,
                concept_id=concept_id,
                tag=tag,
                description=f"Detected misconception: {tag}",
                severity=MisconceptionSeverity.MEDIUM,
            )
            await self.repo.save_misconception(misc)

        # 5. Update Risk Score
        state.risk_score = self.update_risk(
            mastery_score=state.mastery_score,
            retention_score=state.retention_score,
            misconception_count=len(state.misconception_tags),
        )

        # 6. Determine Status & Spaced Review Interval
        state.status = self.engine.determine_status(
            mastery_score=state.mastery_score,
            evidence_count=state.evidence_count,
            risk_score=state.risk_score,
        )
        state.next_review_at = self.engine.calculate_next_review(
            mastery_score=state.mastery_score,
            evidence_count=state.evidence_count,
            now=now,
        )

        await self.repo.save_concept_state(state)
        logger.info(
            f"Recalibrated Learner Model for concept {concept_id} (User: {user_id}): "
            f"Mastery={state.mastery_score}%, Confidence={state.confidence_score}%, "
            f"Retention={state.retention_score}%, Risk={state.risk_score}%, Status={state.status.value}"
        )
        return state

    async def update_state_from_evaluation(
        self,
        user_id: str,
        concept_id: str,
        evaluation: EvaluationResult,
        self_confidence: Optional[float] = None,
    ) -> LearnerConceptState:
        """Compatibility bridge for session evaluation."""
        dummy_evidence = EvidenceRecord(
            id=f"evd_{uuid.uuid4().hex[:8]}",
            user_id=user_id,
            concept_id=concept_id,
            session_id=None,
            evidence_type=EvidenceType.PRACTICE,
            score=evaluation.score,
            feedback=evaluation.feedback,
            reasoning_score=evaluation.reasoning_score,
            transfer_score=evaluation.transfer_score,
            misconceptions_detected=evaluation.misconceptions_detected,
        )
        return await self.on_evidence_recorded(
            user_id=user_id,
            concept_id=concept_id,
            new_evidence=dummy_evidence,
            self_confidence=self_confidence,
        )

    async def get_learner_twin(self, user_id: str) -> LearnerTwinResponse:
        """Assembles the complete Learner Twin state for GET /api/v1/twin."""
        states = await self.repo.list_states_for_user(user_id)
        all_concepts = await self.concept_repo.list_all()
        concept_map = {c.id: c.name for c in all_concepts}

        concept_summaries = []
        weaknesses = []
        now = datetime.now(timezone.utc)

        for s in states:
            # Refresh retention decay dynamically
            s.retention_score = self.update_retention(s.last_seen_at, s.evidence_count, now=now)
            s.risk_score = self.update_risk(s.mastery_score, s.retention_score, len(s.misconception_tags))
            s.status = self.engine.determine_status(s.mastery_score, s.evidence_count, s.risk_score)
            await self.repo.save_concept_state(s)

            concept_name = concept_map.get(s.concept_id, s.concept_id.replace("concept_", "").replace("_", " ").title())

            summary = ConceptMasterySummary(
                concept_id=s.concept_id,
                concept_name=concept_name,
                mastery_score=s.mastery_score,
                confidence_score=s.confidence_score,
                retention_score=s.retention_score,
                risk_score=s.risk_score,
                status=s.status,
                evidence_count=s.evidence_count,
                last_seen_at=s.last_seen_at,
                next_review_at=s.next_review_at,
            )
            concept_summaries.append(summary)

            # Highlight as weakness if risk is high or active misconceptions exist
            if s.risk_score >= 50.0 or s.misconception_tags:
                weaknesses.append(
                    WeaknessItem(
                        concept_id=s.concept_id,
                        concept_name=concept_name,
                        reason="High memory decay" if s.retention_score < 50.0 else "Needs conceptual clarification",
                        risk_score=s.risk_score,
                        misconceptions=s.misconception_tags,
                    )
                )

        overall_mastery = (
            round(sum(s.mastery_score for s in states) / len(states), 1)
            if states else 0.0
        )
        mastered_count = sum(1 for s in states if s.status == LearnerConceptStatus.MASTERED)
        high_risk_count = sum(1 for s in states if s.risk_score >= 60.0)

        # Recent evidence proofs across all concepts
        all_sessions = await self.session_repo.list_by_user_id(user_id)
        recent_evidence_schemas = []
        for sess in all_sessions[-5:]:
            for evd in sess.evidence:
                recent_evidence_schemas.append(
                    EvidenceSchema(
                        id=evd.id,
                        concept_id=evd.concept_id,
                        evidence_type=evd.evidence_type,
                        score=evd.score,
                        feedback=evd.feedback,
                        reasoning_score=evd.reasoning_score,
                        transfer_score=evd.transfer_score,
                        misconceptions_detected=evd.misconceptions_detected,
                        created_at=evd.created_at,
                    )
                )

        return LearnerTwinResponse(
            user_id=user_id,
            overall_mastery=overall_mastery,
            concepts_tracked=len(states),
            concepts_mastered=mastered_count,
            high_retention_risk_count=high_risk_count,
            concepts=concept_summaries,
            weaknesses=weaknesses,
            recent_evidence=recent_evidence_schemas,
        )

    async def get_learner_overview(self, user_id: str) -> LearnerTwinOverview:
        states = await self.repo.list_states_for_user(user_id)
        if not states:
            return LearnerTwinOverview(user_id=user_id)

        overall_mastery = sum(s.mastery_score for s in states) / len(states)
        mastered_count = sum(1 for s in states if s.status == LearnerConceptStatus.MASTERED)
        high_risk_count = sum(1 for s in states if s.risk_score >= 60.0)

        return LearnerTwinOverview(
            user_id=user_id,
            overall_mastery=round(overall_mastery, 1),
            concepts_tracked=len(states),
            concepts_mastered=mastered_count,
            high_retention_risk_count=high_risk_count,
        )


learner_service = LearnerService()
