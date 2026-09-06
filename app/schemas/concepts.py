from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict
from app.domain.learner.models import RetentionRisk, LearnerConceptStatus, MisconceptionSeverity, MisconceptionStatus
from app.schemas.sessions import EvidenceSchema


class MisconceptionSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    concept_id: str
    tag: str
    description: str
    severity: MisconceptionSeverity
    status: MisconceptionStatus
    detected_at: datetime


class ConceptDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    description: str
    domain: str
    difficulty_level: str
    prerequisites: List[str]

    # Learner Twin state for this concept:
    mastery: float
    confidence: float
    retention_risk: RetentionRisk
    status: LearnerConceptStatus
    evidence_count: int

    # Multi-factor score metrics:
    mastery_score: float = 0.0
    confidence_score: float = 0.0
    retention_score: float = 100.0
    risk_score: float = 0.0
    last_seen_at: Optional[datetime] = None
    next_review_at: Optional[datetime] = None
    last_evidence_at: Optional[datetime] = None

    misconceptions: List[MisconceptionSchema] = []
    evidence_history: List[EvidenceSchema] = []
    mentor_recommendation: Optional[str] = None
