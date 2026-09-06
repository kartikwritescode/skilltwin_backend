from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict

class MaintenanceAction(str, Enum):
    KEEP = "KEEP"
    REVISE = "REVISE"
    FIX = "FIX"
    LEARN_NEXT = "LEARN_NEXT"
    DEPRIORITIZE = "DEPRIORITIZE"

class ConceptMaintenanceItem(BaseModel):
    concept_id: str
    concept_name: str
    action: MaintenanceAction
    priority: int
    reason: str
    mastery_score: float
    retention_score: float
    misconceptions: List[str] = Field(default_factory=list)
    journey_position: str
    is_goal_relevant: bool = True
    recommended_time_minutes: int = 15

class KnowledgeMaintenanceResponse(BaseModel):
    user_id: str
    generated_at: datetime
    total_concepts: int
    breakdown: Dict[str, int]
    items: List[ConceptMaintenanceItem]

class GenerateNotesRequest(BaseModel):
    concept_id: str
    force_regenerate: bool = False

class PersonalizedStudyNotesResponse(BaseModel):
    concept_id: str
    title: str
    summary: str
    key_points: List[str]
    your_weakness: str
    remember_this: str
    next_action: str
    cached: bool = False
    generated_at: datetime
