from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any, List


class RelationshipType(str, Enum):
    PREREQUISITE = "prerequisite"
    RELATED = "related"
    PART_OF = "part_of"


@dataclass
class ConceptEdge:
    source_id: str
    target_id: str
    relationship_type: RelationshipType = RelationshipType.PREREQUISITE
    weight: float = 1.0


@dataclass
class Concept:
    id: str
    name: str
    description: str
    domain: str
    difficulty_level: str = "intermediate"
    prerequisites: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
