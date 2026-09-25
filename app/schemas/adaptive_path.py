from datetime import datetime, date
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field, ConfigDict


# ============================================================================
# Canonical & Micro-Subgraph Schemas
# ============================================================================

class MicroSubgraphBase(BaseModel):
    slug: str = Field(..., min_length=2, max_length=64, description="Unique slug for the micro-subgraph")
    title: str = Field(..., min_length=2, max_length=128)
    tier: Literal["foundational", "core", "advanced", "elective"] = Field(
        default="core",
        description="Curriculum hierarchy tier",
    )
    estimated_minutes: int = Field(default=60, ge=5, le=600)
    prerequisites: List[str] = Field(default_factory=list, description="List of prerequisite micro-subgraph slugs")


class MicroSubgraphCreate(MicroSubgraphBase):
    id: Optional[str] = None
    ontology_id: Optional[str] = None


class SynthesizedConceptItem(BaseModel):
    concept_id: str = Field(..., description="Unique concept identifier, e.g. concept_rust_riscv_registers")
    title: str = Field(..., description="Concise milestone concept title")
    estimated_minutes: int = Field(default=30, ge=10, le=120)
    prerequisites: List[str] = Field(default_factory=list, description="IDs of antecedent concepts in this subgraph")


class SynthesizedSubgraphSchema(BaseModel):
    slug: str = Field(..., description="Kebab-case slug, e.g. embedded-rust-riscv")
    title: str = Field(..., description="Sub-graph title, e.g. Embedded Rust for RISC-V Microcontrollers")
    tier: Literal["foundational", "core", "advanced"] = "core"
    estimated_minutes: int = Field(default=60, ge=15, le=360)
    prerequisites: List[str] = Field(default_factory=list, description="External prerequisite subgraph slugs")
    concepts: List[SynthesizedConceptItem] = Field(
        default_factory=list,
        description="3 to 5 sequentially ordered milestone concepts forming a strict DAG"
    )


class MicroSubgraphRead(MicroSubgraphBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    ontology_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CanonicalOntologyBase(BaseModel):
    id: str
    domain: str
    title: str
    description: Optional[str] = None
    total_nodes: int = 0


class CanonicalOntologyRead(CanonicalOntologyBase):
    model_config = ConfigDict(from_attributes=True)

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    subgraphs: List[MicroSubgraphRead] = Field(default_factory=list)


# ============================================================================
# Elaborated Topic & Content Cache Schemas
# ============================================================================

class PracticeQuestionOption(BaseModel):
    id: str
    text: str
    is_correct: bool
    explanation: Optional[str] = None


class PracticeQuestion(BaseModel):
    id: str
    question: str
    options: List[PracticeQuestionOption]
    explanation: Optional[str] = None
    misconception_tag: Optional[str] = None


class CodeChallengeTestCase(BaseModel):
    input: str
    expected_output: str
    explanation: Optional[str] = None


class CodeChallenge(BaseModel):
    id: str
    title: str
    instructions: str
    starter_code: str
    solution_code: Optional[str] = None
    test_cases: List[CodeChallengeTestCase] = Field(default_factory=list)


class ElaboratedTopicContent(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    concept_id: str
    difficulty: Literal["beginner", "intermediate", "advanced"] = "intermediate"
    explanation_markdown: str = Field(..., min_length=10)
    key_invariants: List[str] = Field(default_factory=list)
    practice_questions: List[PracticeQuestion] = Field(default_factory=list)
    code_challenges: List[CodeChallenge] = Field(default_factory=list)
    prompt_version: int = 1
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ============================================================================
# Dynamic Path Node & Edge Schemas
# ============================================================================

NodeState = Literal[
    "LOCKED",
    "AVAILABLE",
    "CURRENT",
    "COMPLETED",
    "NEEDS_REVISION",
    "REMEDIATING",
    "BYPASSED",
]

EdgeType = Literal["prerequisite", "remediation_detour", "recommendation"]


class PathNodeBase(BaseModel):
    concept_id: str
    title: str
    subgraph_id: Optional[str] = None
    state: NodeState = "LOCKED"
    order_index: int
    is_remediation: bool = False
    spliced_after_node_id: Optional[str] = None
    is_elaborated: bool = False
    mastery_score: float = 0.0
    time_spent_minutes: int = 0
    node_metadata: Dict[str, Any] = Field(default_factory=dict)


class PathNodeCreate(PathNodeBase):
    id: Optional[str] = None
    path_id: Optional[str] = None


class PathNodeRead(PathNodeBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    path_id: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class PathNodeEdgeBase(BaseModel):
    source_node_id: str
    target_node_id: str
    edge_type: EdgeType = "prerequisite"


class PathNodeEdgeCreate(PathNodeEdgeBase):
    id: Optional[str] = None
    path_id: Optional[str] = None


class PathNodeEdgeRead(PathNodeEdgeBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    path_id: str
    created_at: Optional[datetime] = None


# ============================================================================
# Adaptive Learning Path Schemas
# ============================================================================

class AdaptiveLearningPathBase(BaseModel):
    title: str
    target_deadline: Optional[date] = None
    daily_budget_minutes: int = Field(default=30, ge=5, le=480)
    velocity_factor: float = Field(default=1.0, ge=0.1, le=5.0)
    path_metadata: Dict[str, Any] = Field(default_factory=dict)


class AdaptiveLearningPathCreate(AdaptiveLearningPathBase):
    user_id: str
    goal_id: str


class AdaptiveLearningPathRead(AdaptiveLearningPathBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    goal_id: str
    status: str = "ACTIVE"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    nodes: List[PathNodeRead] = Field(default_factory=list)
    edges: List[PathNodeEdgeRead] = Field(default_factory=list)
    velocity_metrics: Optional[Dict[str, Any]] = None


class AdaptivePathGenerateRequest(BaseModel):
    goal_id: str = Field(..., description="ID of the user learning goal to generate the ADAG path for")
    target_deadline: Optional[date] = Field(default=None, description="Optional target completion deadline")
    daily_budget_minutes: Optional[int] = Field(default=30, ge=5, le=480, description="Daily study budget in minutes")


class EvidenceSubmissionRequest(BaseModel):
    score: float = Field(..., ge=0.0, le=1.0, description="Evaluation or quiz score between 0.0 and 1.0")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="Confidence rating between 0.0 and 1.0")
    duration_seconds: int = Field(default=120, ge=1, description="Time spent solving or presenting in seconds")
    misconceptions: List[str] = Field(default_factory=list, description="Diagnostic misconception tags detected")


class PacingStatusResponse(BaseModel):
    timeline: Dict[str, Any]
    alert: Optional[Dict[str, Any]] = None
