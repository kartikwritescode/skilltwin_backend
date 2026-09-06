from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any, List


class RetentionRisk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class LearnerConceptStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    LEARNING = "LEARNING"
    MASTERED = "MASTERED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class MisconceptionSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class MisconceptionStatus(str, Enum):
    ACTIVE = "active"
    RESOLVED = "resolved"


@dataclass
class LearnerConceptState:
    """
    Core Learner Model representing live mastery, confidence calibration,
    retention decay, and risk metrics for a single concept.
    """
    user_id: str
    concept_id: str
    mastery_score: float = 0.0      # 0.0 to 100.0
    confidence_score: float = 0.0   # 0.0 to 100.0 (self-reported or calibrated)
    retention_score: float = 100.0  # 0.0 to 100.0 (memory decay tracking)
    risk_score: float = 0.0         # 0.0 to 100.0 (probability of failure/decay)
    status: LearnerConceptStatus = LearnerConceptStatus.NOT_STARTED
    misconception_tags: List[str] = field(default_factory=list)
    evidence_count: int = 0
    last_seen_at: Optional[datetime] = None
    next_review_at: Optional[datetime] = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def mastery(self) -> float:
        """Backwards compatibility alias for mastery_score."""
        return self.mastery_score

    @mastery.setter
    def mastery(self, val: float):
        self.mastery_score = val

    @property
    def confidence(self) -> float:
        """Backwards compatibility alias for confidence_score."""
        return self.confidence_score

    @confidence.setter
    def confidence(self, val: float):
        self.confidence_score = val

    @property
    def retention_risk(self) -> RetentionRisk:
        """Derive categorical RetentionRisk from risk_score."""
        if self.risk_score >= 60.0 or self.retention_score < 40.0:
            return RetentionRisk.HIGH
        elif self.risk_score >= 30.0 or self.retention_score < 70.0:
            return RetentionRisk.MEDIUM
        return RetentionRisk.LOW

    @retention_risk.setter
    def retention_risk(self, val: RetentionRisk):
        if val == RetentionRisk.HIGH:
            self.risk_score = max(self.risk_score, 70.0)
            self.retention_score = min(self.retention_score, 35.0)
        elif val == RetentionRisk.MEDIUM:
            self.risk_score = 45.0
            self.retention_score = 60.0
        else:
            self.risk_score = 15.0
            self.retention_score = 90.0


@dataclass
class Misconception:
    id: str
    user_id: str
    concept_id: str
    tag: str
    description: str
    severity: MisconceptionSeverity = MisconceptionSeverity.MEDIUM
    status: MisconceptionStatus = MisconceptionStatus.ACTIVE
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved_at: Optional[datetime] = None


@dataclass
class LearnerTwinOverview:
    user_id: str
    overall_mastery: float = 0.0
    concepts_tracked: int = 0
    concepts_mastered: int = 0
    high_retention_risk_count: int = 0
    active_misconceptions: List[Misconception] = field(default_factory=list)
