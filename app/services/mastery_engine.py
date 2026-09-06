import math
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from app.domain.learner.models import LearnerConceptState, LearnerConceptStatus
from app.domain.sessions.models import EvidenceRecord, EvidenceType
from app.core.logging import logger


class MasteryEngine:
    """
    Deterministic & Extensible Pedagogical Mastery Engine.

    Conceptual Scoring Model:
      mastery = correctness + consistency + application + explanation + delayed retrieval

    Confidence is tracked independently from correctness to identify calibration gaps
    (e.g., overconfidence or imposter syndrome).
    """

    # Weights by evidence type reflecting cognitive depth
    EVIDENCE_TYPE_WEIGHTS = {
        EvidenceType.RECALL: 0.8,
        EvidenceType.ASSESSMENT: 1.0,
        EvidenceType.PRACTICE: 1.2,
        EvidenceType.EXPLANATION: 1.3,
        EvidenceType.TEACH_BACK: 1.4,
        EvidenceType.PROJECT: 1.5,
        EvidenceType.DELAYED_RETRIEVAL: 1.4,
    }

    def update_mastery(
        self,
        existing_state: LearnerConceptState,
        evidence_history: List[EvidenceRecord],
        new_evidence: EvidenceRecord,
    ) -> float:
        """
        Calculates new mastery score [0.0 - 100.0] combining:
        1. Correctness (raw score)
        2. Application weight (Project / Practice proofs)
        3. Explanation weight (Teach-Back / Explanation proofs)
        4. Consistency bonus (low variance across recent attempts)
        5. Delayed retrieval bonus (long-term memory proof)
        """
        type_weight = self.EVIDENCE_TYPE_WEIGHTS.get(new_evidence.evidence_type, 1.0)
        raw_correctness = new_evidence.score

        # 1. Component: Correctness scaled by cognitive depth
        weighted_score = min(100.0, raw_correctness * type_weight)

        # 2. Component: Consistency across recent evidence
        all_proofs = evidence_history + [new_evidence]
        recent_scores = [p.score for p in all_proofs[-4:]]
        avg_recent = sum(recent_scores) / len(recent_scores)
        consistency_bonus = 0.0
        if len(recent_scores) >= 2 and all(s >= 70.0 for s in recent_scores):
            # Reward repeated reliable performance
            consistency_bonus = 5.0

        # 3. Component: Application / Transfer evidence check
        has_application = any(p.evidence_type in (EvidenceType.PRACTICE, EvidenceType.PROJECT) for p in all_proofs)
        application_bonus = 4.0 if has_application and raw_correctness >= 75.0 else 0.0

        # 4. Component: Explanation / Mental model check
        has_explanation = any(p.evidence_type in (EvidenceType.EXPLANATION, EvidenceType.TEACH_BACK) for p in all_proofs)
        explanation_bonus = 4.0 if has_explanation and raw_correctness >= 75.0 else 0.0

        # Composite target score
        target_score = min(100.0, (weighted_score * 0.85) + consistency_bonus + application_bonus + explanation_bonus)

        # Blend with prior mastery using momentum based on accumulated evidence
        evidence_count = existing_state.evidence_count + 1
        momentum = min(0.75, 0.30 + (0.08 * evidence_count))

        if existing_state.evidence_count == 0:
            new_mastery = target_score
        else:
            new_mastery = (existing_state.mastery_score * (1.0 - momentum)) + (target_score * momentum)

        return round(max(0.0, min(100.0, new_mastery)), 1)

    def update_confidence(
        self,
        existing_confidence: float,
        self_reported_confidence: Optional[float],
        evidence_score: float,
    ) -> float:
        """
        Calibrates confidence separately from correctness.
        Integrates subjective self-assessment with objective test evidence.
        """
        if self_reported_confidence is not None:
            # Calibrate: pull self-reported towards objective score to improve metacognition
            calibrated_target = (self_reported_confidence * 0.6) + (evidence_score * 0.4)
        else:
            calibrated_target = evidence_score

        if existing_confidence == 0.0:
            return round(max(0.0, min(100.0, calibrated_target)), 1)

        new_conf = (existing_confidence * 0.5) + (calibrated_target * 0.5)
        return round(max(0.0, min(100.0, new_conf)), 1)

    def update_retention(
        self,
        last_seen_at: Optional[datetime],
        evidence_count: int,
        now: Optional[datetime] = None,
    ) -> float:
        """
        Ebbinghaus-inspired memory retention decay:
        R = 100 * e^(-k * t)
        Higher evidence counts reduce decay rate k.
        """
        current_time = now or datetime.now(timezone.utc)
        if not last_seen_at:
            return 100.0

        elapsed_days = max(0.0, (current_time - last_seen_at).total_seconds() / 86400.0)
        # Decay constant shrinks as repetitions grow
        k = 0.25 / (1.0 + (0.5 * evidence_count))
        retention = 100.0 * math.exp(-k * elapsed_days)

        return round(max(0.0, min(100.0, retention)), 1)

    def update_risk(
        self,
        mastery_score: float,
        retention_score: float,
        misconception_count: int,
    ) -> float:
        """
        Computes composite knowledge risk score [0.0 - 100.0].
        Higher score = higher probability of forgetting or failing milestone proofs.
        """
        retention_deficit = (100.0 - retention_score) * 0.45
        mastery_deficit = (100.0 - mastery_score) * 0.35
        misconception_penalty = min(20.0, misconception_count * 10.0)

        risk = retention_deficit + mastery_deficit + misconception_penalty
        return round(max(0.0, min(100.0, risk)), 1)

    def determine_status(
        self,
        mastery_score: float,
        evidence_count: int,
        risk_score: float,
    ) -> LearnerConceptStatus:
        """Categorizes learner status based on empirical thresholds."""
        if risk_score >= 60.0 and evidence_count > 0:
            return LearnerConceptStatus.NEEDS_REVIEW
        if mastery_score >= 85.0 and evidence_count >= 3:
            return LearnerConceptStatus.MASTERED
        if evidence_count > 0:
            return LearnerConceptStatus.LEARNING
        return LearnerConceptStatus.NOT_STARTED

    def calculate_next_review(
        self,
        mastery_score: float,
        evidence_count: int,
        now: Optional[datetime] = None,
    ) -> datetime:
        """Schedules optimal spaced retrieval practice interval."""
        current_time = now or datetime.now(timezone.utc)
        if mastery_score >= 85.0:
            days = 7 * max(1, evidence_count - 1)
        elif mastery_score >= 60.0:
            days = 3 * max(1, evidence_count - 1)
        else:
            days = 1

        return current_time + timedelta(days=days)


mastery_engine = MasteryEngine()
