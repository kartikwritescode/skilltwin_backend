from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict
from app.domain.goals.models import GoalStatus
from app.domain.journeys.models import GenerationStatus


class GoalCreateRequest(BaseModel):
    title: str = Field(
        ...,
        min_length=3,
        max_length=200,
        json_schema_extra={"example": "Become a Senior Flutter Engineer"}
    )
    description: Optional[str] = Field(
        None,
        json_schema_extra={"example": "Master architecture, state management, and async performance"}
    )
    deadline: Optional[str] = Field(
        None,
        json_schema_extra={"example": "2026-12-31"}
    )
    daily_minutes: int = Field(
        default=30,
        ge=5,
        le=480,
        json_schema_extra={"example": 30}
    )
    current_level: str = Field(
        default="beginner",
        json_schema_extra={"example": "intermediate"}
    )
    existing_knowledge: Optional[str] = Field(
        None,
        json_schema_extra={"example": "Comfortable with basic Dart and UI widgets"}
    )
    constraints: Optional[List[str]] = Field(
        default_factory=list,
        json_schema_extra={"example": ["Only weekdays", "No videos longer than 15 min"]}
    )


class GoalUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=3, max_length=200)
    description: Optional[str] = None
    deadline: Optional[str] = None
    daily_minutes: Optional[int] = Field(None, ge=5, le=480)
    current_level: Optional[str] = None
    existing_knowledge: Optional[str] = None
    constraints: Optional[List[str]] = None
    status: Optional[GoalStatus] = None


class GoalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: str
    title: str
    description: Optional[str] = None
    deadline: Optional[str] = None
    daily_minutes: int
    current_level: str
    existing_knowledge: Optional[str] = None
    constraints: List[str] = Field(default_factory=list)
    status: GoalStatus
    active_journey_id: Optional[str] = None
    generation_status: GenerationStatus = GenerationStatus.PENDING
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
