from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict
from app.domain.sessions.models import SessionType, SessionStatus, EvidenceType, SessionStepType
from app.schemas.mentor import ActionRecommendationSchema


class SessionCreateRequest(BaseModel):
    recommendation_id: Optional[str] = Field(None, json_schema_extra={"example": "rec_abc123"})
    session_type: Optional[SessionType] = Field(None, json_schema_extra={"example": "REMEDIATE"})
    concept_id: Optional[str] = Field(None, json_schema_extra={"example": "concept_dart_async_and_streams"})
    goal_id: Optional[str] = Field(None, json_schema_extra={"example": "goal_flutter_pro"})
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)


class SessionStepSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    order: int
    step_type: SessionStepType
    title: str
    instruction: str
    prompt: str
    question_type: str = "open_ended"
    options: List[str] = Field(default_factory=list)
    rubric_criteria: Optional[str] = ""
    user_response: Optional[str] = None
    evaluation_score: Optional[float] = None
    feedback: Optional[str] = None


class SessionCompleteRequest(BaseModel):
    user_submission: Optional[str] = Field(None, description="Explanation, code, or answers submitted by learner")
    step_responses: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Optional step-by-step answers")
    time_spent_seconds: int = Field(default=300, ge=0, description="Time spent in session in seconds")
    self_reported_confidence: Optional[float] = Field(default=75.0, ge=0.0, le=100.0)
    quiz_results: Optional[List[Dict[str, Any]]] = Field(default_factory=list)


class EvidenceSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    concept_id: str
    evidence_type: EvidenceType
    score: float
    feedback: str
    reasoning_score: Optional[float] = None
    transfer_score: Optional[float] = None
    misconceptions_detected: List[str] = Field(default_factory=list)
    created_at: datetime


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: str
    goal_id: Optional[str] = None
    concept_id: str
    session_type: SessionType
    status: SessionStatus
    recommendation_id: Optional[str] = None
    steps: List[SessionStepSchema] = Field(default_factory=list)
    started_at: datetime
    completed_at: Optional[datetime] = None
    score: Optional[float] = None
    evidence: List[EvidenceSchema] = Field(default_factory=list)
    mastery_delta: Optional[float] = Field(None, description="Change in learner mastery resulting from this session")
    next_recommended_step: Optional[str] = None
    next_recommendation: Optional[ActionRecommendationSchema] = None

