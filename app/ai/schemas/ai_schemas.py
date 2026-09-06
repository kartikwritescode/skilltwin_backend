from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class GeneratedJourneyNode(BaseModel):
    title: str
    description: str
    phase: str
    order: int
    concept_name: str
    estimated_minutes: int = 25
    position_x: float = 0.5
    position_y: float = 0.0


class GeneratedJourneyEdge(BaseModel):
    source_order: int
    target_order: int
    edge_type: str = "next"


class GeneratedJourneyPlan(BaseModel):
    goal_title: str
    nodes: List[GeneratedJourneyNode]
    edges: List[GeneratedJourneyEdge] = Field(default_factory=list)
    summary: str


class StepEvaluation(BaseModel):
    step_id: Optional[str] = ""
    question: Optional[str] = ""
    user_answer: Optional[str] = ""
    is_correct: bool = False
    correct_answer: str = ""
    explanation: str = ""


class EvaluationResult(BaseModel):
    score: float = Field(..., ge=0.0, le=100.0)
    reasoning_score: float = Field(default=0.0, ge=0.0, le=100.0)
    transfer_score: float = Field(default=0.0, ge=0.0, le=100.0)
    accuracy_score: float = Field(default=0.0, ge=0.0, le=100.0)
    completeness_score: float = Field(default=0.0, ge=0.0, le=100.0)
    feedback: str
    improvements: List[str] = Field(default_factory=list)
    focus_areas: List[str] = Field(default_factory=list)
    misconceptions_detected: List[str] = Field(default_factory=list)
    resolved_misconceptions: List[str] = Field(default_factory=list)
    mastery_delta: float = Field(default=0.0)
    confidence_delta: float = Field(default=0.0)
    step_evaluations: List[StepEvaluation] = Field(default_factory=list)


class GeneratedSessionStep(BaseModel):
    order: int
    step_type: str = Field(
        ...,
        description="Must be one of: RECALL, EXPLAIN, PRACTICE, DIAGNOSE, APPLY, TRANSFER, TEACH"
    )
    title: str
    instruction: str
    prompt: str
    question_type: str = Field(default="open_ended", description="open_ended, multiple_choice, code_fix, diagnosis")
    options: List[str] = Field(default_factory=list)
    rubric_criteria: str = ""
    correct_answer: str = Field(default="", description="The correct answer or ideal solution")
    explanation: str = Field(default="", description="Pedagogical explanation of why this is correct")


class GeneratedSessionPlan(BaseModel):
    session_title: str
    session_type: str
    concept_id: str
    concept_name: str
    pedagogical_focus: str
    estimated_minutes: int = 20
    steps: List[GeneratedSessionStep]


class ExtractedConcept(BaseModel):
    name: str
    description: str
    difficulty_level: str = "intermediate"
    prerequisites: List[str] = Field(default_factory=list)
    relevance_score: float = Field(default=0.9, ge=0.0, le=1.0)


class ExtractedConceptList(BaseModel):
    concepts: List[ExtractedConcept]
    primary_domain: str = "Software Engineering"
    summary: str = ""


class MentorRecommendationOutput(BaseModel):
    intent: str = Field(
        ...,
        description="Recommendation intent: LEARN, REVISE, PRACTICE, PROVE, TEACH, REMEDIATE, SKIP, REFLECT"
    )
    concept_id: str
    title: str
    reason: str
    estimated_minutes: int
    confidence: float = Field(default=0.92, ge=0.0, le=1.0)


class MentorChatAIOutput(BaseModel):
    reply: str
    suggested_intent: Optional[str] = None
    suggested_concept_id: Optional[str] = None
    suggested_title: Optional[str] = None
    suggested_reason: Optional[str] = None
    estimated_minutes: Optional[int] = 20


class MentorDecisionAIOutput(BaseModel):
    reply: str
    action_type: str = "LEARN"
    action_title: str
    action_reason: str
    estimated_minutes: int = 20
    concept_name: Optional[str] = None


class PersonalizedStudyNotesAIOutput(BaseModel):
    title: str
    summary: str
    key_points: List[str]
    your_weakness: str
    remember_this: str
    next_action: str


class TeachEvaluationAIOutput(BaseModel):
    conceptual_accuracy: int = Field(..., ge=0, le=100, description="Factual and technical accuracy of the core concepts")
    completeness: int = Field(..., ge=0, le=100, description="Coverage of necessary mechanisms, invariants, and edge cases")
    reasoning: int = Field(..., ge=0, le=100, description="Logical depth, causal explanations, and why principles hold")
    confidence: int = Field(..., ge=0, le=100, description="Linguistic assertiveness and clarity without false hesitation")
    transfer: int = Field(..., ge=0, le=100, description="Ability to apply or relate the concept to other domains or concrete examples")
    misconceptions: List[str] = Field(default_factory=list, description="Specific diagnosed misconceptions or technical fallacies")
    missing_concepts: List[str] = Field(default_factory=list, description="Critical sub-concepts omitted in the explanation")
    recommendation: str = Field(default="PRACTICE", description="One of: LEARN, REVISE, PRACTICE, PROVE, TEACH, REMEDIATE, SKIP, REFLECT")
    feedback_summary: Optional[str] = None
    key_strengths: List[str] = Field(default_factory=list)
    growth_areas: List[str] = Field(default_factory=list)

