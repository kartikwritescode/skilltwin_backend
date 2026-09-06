from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any, List


class GoalStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    PAUSED = "paused"
    ARCHIVED = "archived"


@dataclass
class Goal:
    id: str
    user_id: str
    title: str
    description: Optional[str] = None
    deadline: Optional[str] = None
    daily_minutes: int = 30
    current_level: str = "beginner"
    existing_knowledge: Optional[str] = None
    constraints: List[str] = field(default_factory=list)
    target_benchmark: Optional[str] = None
    status: GoalStatus = GoalStatus.ACTIVE
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def target_date(self) -> Optional[str]:
        """Backward compatibility alias for deadline."""
        return self.deadline
