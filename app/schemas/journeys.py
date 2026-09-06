from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, ConfigDict
from app.domain.journeys.models import NodeState, JourneyStatus, GenerationStatus


class JourneyNodeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    subtitle: str = ""
    phase: str
    state: NodeState
    progress: int = 0
    concept_id: str
    estimated_minutes: int = 20
    prerequisites: List[str] = []
    is_remediation: bool = False
    order: Optional[int] = None
    position_x: Optional[float] = 0.5
    position_y: Optional[float] = 0.0


class JourneyNodeUpdate(BaseModel):
    state: Optional[NodeState] = None
    progress: Optional[int] = None


class JourneyEdgeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    source_node_id: str
    target_node_id: str
    edge_type: str = "prerequisite"


class JourneyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    goal_id: str
    title: str
    progress: int = 0
    nodes: List[JourneyNodeResponse] = []
    edges: List[JourneyEdgeResponse] = []
    status: JourneyStatus = JourneyStatus.ACTIVE
    generation_status: GenerationStatus = GenerationStatus.READY
    generation_error: Optional[str] = None
