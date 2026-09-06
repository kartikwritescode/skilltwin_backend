from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict
from app.domain.mentor.models import ActionType, MentorRole


class ActionRecommendationSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    action_type: ActionType
    title: str
    reason: str
    estimated_minutes: int
    concept_id: Optional[str] = None
    node_id: Optional[str] = None
    priority: int = 1
    quick_action_label: str = "Start Now"


class MentorTodayResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    greeting: str
    mentor_note: str
    current_goal_title: Optional[str] = None
    current_goal_progress: float = 0.0
    recommended_action: ActionRecommendationSchema
    alternative_actions: List[ActionRecommendationSchema] = Field(default_factory=list)
    candidate_rankings: List[Dict[str, Any]] = Field(default_factory=list)
    deadline_pressure: str = "normal"
    pipeline_steps_executed: int = 14
    daily_checklist: List[str] = Field(default_factory=list)


class MentorMessageRequest(BaseModel):
    message: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        json_schema_extra={"example": "Why did you recommend recursion today?"}
    )
    context: Optional[Dict[str, Any]] = Field(default_factory=dict)


class MentorMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    role: MentorRole = MentorRole.MENTOR
    content: str
    suggested_actions: List[ActionRecommendationSchema] = Field(default_factory=list)
    created_at: datetime
