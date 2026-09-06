from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict, Field
from app.domain.revision.models import RetrievalResult, RetrievalAccuracy, RetrievalConfidence


class ReviewItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    concept_id: str
    concept_name: str
    last_reviewed: Optional[datetime] = None
    next_review: datetime
    interval: int = 1
    successful_retrievals: int = 0
    failed_retrievals: int = 0
    retention_score: float = 100.0
    priority_score: float = 0.0
    is_high_priority: bool = False
    retention_risk: str = "medium"
    why_today: str = "Memory decay threshold reached. Spaced retrieval anchors foundational invariants."
    mentor_prompt: Optional[str] = None
    estimated_minutes: int = 4
    next_review_text: Optional[str] = None

    # Backward compatibility aliases
    due_at: Optional[datetime] = None
    interval_days: Optional[int] = None
    repetitions: Optional[int] = None
    last_reviewed_at: Optional[datetime] = None
    ease_factor: Optional[float] = 2.5

    def model_post_init(self, __context):
        if self.due_at is None:
            self.due_at = self.next_review
        if self.interval_days is None:
            self.interval_days = self.interval
        if self.last_reviewed_at is None:
            self.last_reviewed_at = self.last_reviewed
        if self.repetitions is None:
            self.repetitions = self.successful_retrievals + self.failed_retrievals


class RevisionNextResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    header: str = "5 minutes for your future self."
    total_due_count: int
    primary_review_item: Optional[ReviewItemResponse] = None
    upcoming_items: List[ReviewItemResponse] = []
    mentor_guidance: str = "Consistent 5-minute retrieval is the single highest-yield cognitive investment."


class ReviewCompleteRequest(BaseModel):
    is_successful: bool = Field(..., description="True if retrieval was correct/successful, False if failed")
    confidence: Optional[float] = Field(default=None, ge=0.0, le=100.0, description="Self-reported confidence percentage")
    time_spent_seconds: int = Field(default=120, description="Time spent on retrieval practice")
    notes: Optional[str] = None


class ReviewSubmissionRequest(BaseModel):
    review_item_id: str
    result: Optional[RetrievalResult] = None
    accuracy: Optional[RetrievalAccuracy] = None
    confidence: Optional[RetrievalConfidence] = None
    time_spent_seconds: int = 120
    notes: Optional[str] = None


class MentorNotification(BaseModel):
    id: str
    title: str
    message: str
    concept_id: Optional[str] = None
    notification_type: str = "REVISION_DUE"
    created_at: datetime
    is_read: bool = False
    action_url: str = "/revision"


class MentorNotificationsResponse(BaseModel):
    unread_count: int
    notifications: List[MentorNotification]
