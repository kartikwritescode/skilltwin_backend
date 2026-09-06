from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, Dict, Any


class NodeState(str, Enum):
    LOCKED = "LOCKED"
    AVAILABLE = "AVAILABLE"
    CURRENT = "CURRENT"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"


class JourneyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    PAUSED = "PAUSED"


class GenerationStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"


@dataclass
class JourneyNode:
    id: str
    journey_id: str
    concept_id: str
    title: str
    subtitle: str = ""
    phase: str = "Foundations"
    order: int = 1
    state: NodeState = NodeState.LOCKED
    progress: int = 0  # 0 to 100
    estimated_minutes: int = 20
    prerequisites: List[str] = field(default_factory=list)  # list of prerequisite node IDs
    is_remediation: bool = False
    position_x: float = 0.5
    position_y: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def description(self) -> str:
        """Alias description to subtitle for backwards compatibility."""
        return self.subtitle


@dataclass
class JourneyEdge:
    source_node_id: str
    target_node_id: str
    edge_type: str = "prerequisite"


@dataclass
class Journey:
    id: str
    goal_id: str
    user_id: str
    title: str = ""
    progress: int = 0  # 0 to 100
    version: int = 1
    status: JourneyStatus = JourneyStatus.ACTIVE
    generation_status: GenerationStatus = GenerationStatus.PENDING
    generation_error: Optional[str] = None
    nodes: List[JourneyNode] = field(default_factory=list)
    edges: List[JourneyEdge] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def progress_percentage(self) -> float:
        """Backwards compatibility float alias for progress."""
        return float(self.progress)
