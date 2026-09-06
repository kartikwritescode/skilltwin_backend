from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class RetrievalResult(str, Enum):
    FAIL = "fail"
    HARD = "hard"
    GOOD = "good"
    EASY = "easy"


class RetrievalAccuracy(str, Enum):
    CORRECT = "correct"
    PARTIALLY_CORRECT = "partially_correct"
    INCORRECT = "incorrect"


class RetrievalConfidence(str, Enum):
    CONFIDENT = "confident"
    NOT_CONFIDENT = "not_confident"


@dataclass
class ReviewItem:
    id: str
    user_id: str
    concept_id: str
    concept_name: str
    next_review: datetime
    interval: int = 1
    last_reviewed: Optional[datetime] = None
    successful_retrievals: int = 0
    failed_retrievals: int = 0
    retention_score: float = 100.0
    priority_score: float = 0.0
    is_high_priority: bool = False
    ease_factor: float = 2.5
    last_result: Optional[RetrievalResult] = None
    last_accuracy: Optional[RetrievalAccuracy] = None
    last_confidence: Optional[RetrievalConfidence] = None
    retention_risk: str = "medium"
    why_today: str = "Memory decay threshold reached. Spaced retrieval anchors foundational invariants."
    mentor_prompt: Optional[str] = None
    estimated_minutes: int = 4
    next_review_text: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Aliases for backwards compatibility with earlier journey/revision code
    @property
    def due_at(self) -> datetime:
        return self.next_review

    @due_at.setter
    def due_at(self, val: datetime) -> None:
        self.next_review = val

    @property
    def interval_days(self) -> int:
        return self.interval

    @interval_days.setter
    def interval_days(self, val: int) -> None:
        self.interval = val

    @property
    def last_reviewed_at(self) -> Optional[datetime]:
        return self.last_reviewed

    @last_reviewed_at.setter
    def last_reviewed_at(self, val: Optional[datetime]) -> None:
        self.last_reviewed = val

    @property
    def repetitions(self) -> int:
        return self.successful_retrievals + self.failed_retrievals

    @repetitions.setter
    def repetitions(self, val: int) -> None:
        # If set directly from legacy code
        self.successful_retrievals = val
