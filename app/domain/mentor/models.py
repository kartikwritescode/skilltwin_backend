from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any, List


class MentorRole(str, Enum):
    USER = "user"
    MENTOR = "mentor"
    SYSTEM = "system"


class ActionType(str, Enum):
    LEARN = "LEARN"
    REVISE = "REVISE"
    PRACTICE = "PRACTICE"
    PROVE = "PROVE"
    TEACH = "TEACH"
    REMEDIATE = "REMEDIATE"
    SKIP = "SKIP"
    REFLECT = "REFLECT"


@dataclass
class MentorMessage:
    id: str
    user_id: str
    role: MentorRole
    content: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ActionRecommendation:
    action_type: ActionType
    title: str
    reason: str
    estimated_minutes: int
    concept_id: Optional[str] = None
    node_id: Optional[str] = None
    priority: int = 1
    confidence: float = 0.95
    quick_action_label: str = "Start Now"


@dataclass
class RecommendationRecord:
    """Audit log entity for persistent tracking of mentor recommendations."""
    id: str
    user_id: str
    goal_id: Optional[str]
    concept_id: Optional[str]
    action_type: ActionType
    title: str
    reason: str
    estimated_minutes: int
    confidence: float
    rule_matched: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class MentorDailyBrief:
    user_id: str
    greeting: str
    mentor_note: str
    current_goal_title: Optional[str]
    current_goal_progress: float
    recommended_action: ActionRecommendation
    alternative_actions: List[ActionRecommendation] = field(default_factory=list)
    daily_checklist: List[str] = field(default_factory=list)
