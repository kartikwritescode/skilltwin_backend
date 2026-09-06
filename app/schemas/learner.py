from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, ConfigDict
from app.domain.learner.models import LearnerConceptStatus, RetentionRisk
from app.schemas.sessions import EvidenceSchema


class ConceptMasterySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    concept_id: str
    concept_name: str
    mastery_score: float
    confidence_score: float
    retention_score: float
    risk_score: float
    status: LearnerConceptStatus
    evidence_count: int
    last_seen_at: Optional[datetime] = None
    next_review_at: Optional[datetime] = None


class WeaknessItem(BaseModel):
    concept_id: str
    concept_name: str
    reason: str
    risk_score: float
    misconceptions: List[str] = []


class LearnerTwinResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: str
    overall_mastery: float
    concepts_tracked: int
    concepts_mastered: int
    high_retention_risk_count: int
    concepts: List[ConceptMasterySummary] = []
    weaknesses: List[WeaknessItem] = []
    recent_evidence: List[EvidenceSchema] = []
