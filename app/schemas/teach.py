from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class AudioTranscriptionResponse(BaseModel):
    transcript: str
    duration_seconds: float
    word_count: int
    confidence: float
    detected_language: str = "en"


class TeachEvaluateRequest(BaseModel):
    concept_id: str
    explanation_text: str = Field(..., min_length=5, description="Learner explanation text transcribed or typed")
    audio_duration_seconds: Optional[float] = None
    session_id: Optional[str] = None
    self_reported_confidence: Optional[float] = Field(default=None, ge=0.0, le=100.0)


class TeachEvaluationResponse(BaseModel):
    concept_id: str
    conceptual_accuracy: int
    completeness: int
    reasoning: int
    confidence: int
    transfer: int
    misconceptions: List[str] = Field(default_factory=list)
    missing_concepts: List[str] = Field(default_factory=list)
    recommendation: str
    evidence_id: Optional[str] = None
    updated_mastery_score: float
    updated_confidence_score: float
    updated_status: str
    feedback_summary: Optional[str] = None
    key_strengths: List[str] = Field(default_factory=list)
    growth_areas: List[str] = Field(default_factory=list)
    evaluated_at: datetime
