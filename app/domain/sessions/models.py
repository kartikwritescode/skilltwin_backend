from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any, List


class SessionType(str, Enum):
    LEARN = "LEARN"
    PRACTICE = "PRACTICE"
    PROVE = "PROVE"
    TEACH = "TEACH"
    REMEDIATE = "REMEDIATE"
    REVISE = "REVISE"
    REFLECT = "REFLECT"

    @classmethod
    def _missing_(cls, value):
        # Allow case-insensitive matching (e.g. 'learn', 'practice')
        if isinstance(value, str):
            for member in cls:
                if member.value.lower() == value.lower():
                    return member
        return None


class SessionStepType(str, Enum):
    RECALL = "RECALL"
    EXPLAIN = "EXPLAIN"
    PRACTICE = "PRACTICE"
    DIAGNOSE = "DIAGNOSE"
    APPLY = "APPLY"
    TRANSFER = "TRANSFER"
    TEACH = "TEACH"


class SessionStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class EvidenceType(str, Enum):
    RECALL = "RECALL"
    PRACTICE = "PRACTICE"
    EXPLANATION = "EXPLANATION"
    TEACH_BACK = "TEACH_BACK"
    PROJECT = "PROJECT"
    ASSESSMENT = "ASSESSMENT"
    DELAYED_RETRIEVAL = "DELAYED_RETRIEVAL"


@dataclass
class SessionStep:
    id: str
    order: int
    step_type: SessionStepType
    title: str
    instruction: str
    prompt: str
    question_type: str = "open_ended"  # open_ended, multiple_choice, code_fix, diagnosis
    options: List[str] = field(default_factory=list)
    rubric_criteria: str = ""
    user_response: Optional[str] = None
    evaluation_score: Optional[float] = None
    feedback: Optional[str] = None


@dataclass
class EvidenceRecord:
    id: str
    user_id: str
    concept_id: str
    session_id: Optional[str]
    evidence_type: EvidenceType
    score: float  # 0.0 to 100.0
    feedback: str
    reasoning_score: Optional[float] = None
    transfer_score: Optional[float] = None
    misconceptions_detected: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class LearningSession:
    id: str
    user_id: str
    goal_id: Optional[str]
    concept_id: str
    session_type: SessionType
    status: SessionStatus = SessionStatus.ACTIVE
    recommendation_id: Optional[str] = None
    steps: List[SessionStep] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    score: Optional[float] = None
    evidence: List[EvidenceRecord] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

