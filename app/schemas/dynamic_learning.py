from datetime import datetime, date
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Goal Schemas
# ---------------------------------------------------------------------------

class LearningGoalCreateRequest(BaseModel):
    learning_goal: str = Field(..., description="Free text user goal, e.g. 'Become a backend developer using Django and PostgreSQL'")
    target_level: str = Field(default="Intermediate", description="Beginner, Intermediate, Expert, Interview Ready, Other")
    custom_target: Optional[str] = Field(default=None, description="Custom outcome if target_level is Other or custom target")
    daily_minutes: int = Field(default=30, ge=5, le=480)
    deadline: Optional[date] = Field(default=None, description="Target completion deadline date")
    current_knowledge: List[str] = Field(default_factory=list)
    learning_preferences: Optional[str] = Field(default="Hands-on and project-focused")
    strengths: Optional[str] = Field(default=None)
    weaknesses: Optional[str] = Field(default=None)


class LearningGoalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: str
    learning_goal: str
    target_level: str
    custom_target: Optional[str] = None
    daily_minutes: int
    deadline: Optional[date] = None
    current_knowledge: List[str] = []
    status: str
    active_path_id: Optional[str] = None
    progress: float = 0.0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Hierarchical Learning Path Schemas
# ---------------------------------------------------------------------------

class LearningTopicResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    section_id: str
    title: str
    description: Optional[str] = None
    order_index: int
    difficulty: str = "beginner"
    estimated_minutes: int = 25
    prerequisites: List[str] = []
    learning_objectives: List[str] = []
    key_concepts: List[str] = []
    status: str = "not_started"  # not_started, learning, completed, needs_revision
    mastery_score: float = 0.0
    confidence_score: float = 0.0
    revision_count: int = 0
    completed_at: Optional[datetime] = None
    next_revision_at: Optional[datetime] = None


class LearningSectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    path_id: str
    title: str
    description: Optional[str] = None
    order_index: int
    topics: List[LearningTopicResponse] = []


class LearningPathResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    goal_id: str
    user_id: str
    title: str
    description: Optional[str] = None
    target_level: str = "Intermediate"
    estimated_duration: Optional[str] = None
    version: int = 1
    status: str = "ACTIVE"
    generation_status: str = "READY"
    generation_error: Optional[str] = None
    progress: float = 0.0
    sections: List[LearningSectionResponse] = []
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Topic Detail & Interaction Schemas
# ---------------------------------------------------------------------------

class TopicDetailResponse(BaseModel):
    id: str
    section_id: str
    section_title: str
    path_id: str
    title: str
    description: Optional[str] = None
    order_index: int
    difficulty: str
    estimated_minutes: int
    prerequisites: List[str] = []
    learning_objectives: List[str] = []
    key_concepts: List[str] = []
    status: str  # not_started, learning, completed, needs_revision
    mastery_score: float = 0.0
    confidence_score: float = 0.0
    revision_count: int = 0
    time_spent_minutes: int = 0
    attempts: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    next_revision_at: Optional[datetime] = None
    previous_topic_id: Optional[str] = None
    next_topic_id: Optional[str] = None
    has_cached_explanation: bool = False
    question_count: int = 0


class TopicExplanationResponse(BaseModel):
    topic_id: str
    topic_title: str
    content: str
    prompt_version: str = "v1"
    cached: bool = False
    sources: List[str] = []


class TopicQuestionItem(BaseModel):
    id: str
    topic_id: str
    question_type: str  # mcq, true_false, short_answer, scenario, code_fix, interview
    prompt: str
    options: List[str] = []
    correct_answer: str
    explanation: str
    difficulty: str = "medium"


class TopicQuestionsResponse(BaseModel):
    topic_id: str
    topic_title: str
    questions: List[TopicQuestionItem] = []


class AnswerSubmissionItem(BaseModel):
    question_id: str
    user_answer: str


class QuestionSubmissionRequest(BaseModel):
    answers: List[AnswerSubmissionItem]


class QuestionAttemptResult(BaseModel):
    question_id: str
    is_correct: bool
    score: float
    feedback: str
    correct_answer: str


class QuestionSubmissionResponse(BaseModel):
    topic_id: str
    score: float
    mastery_score: float
    mastery_delta: float
    correct_count: int
    total_count: int
    overall_feedback: str
    attempts: List[QuestionAttemptResult] = []


class TopicStatusUpdateResponse(BaseModel):
    topic_id: str
    status: str
    mastery_score: float
    completed_at: Optional[datetime] = None
    next_revision_at: Optional[datetime] = None
    path_progress: float = 0.0


# ---------------------------------------------------------------------------
# Home & Twin Dashboard Schemas (True Dynamic Metrics)
# ---------------------------------------------------------------------------

class HomeDashboardResponse(BaseModel):
    goal_id: Optional[str] = None
    goal_title: str = "No Active Goal"
    target_level: str = "Beginner"
    current_module_name: Optional[str] = None
    current_topic_id: Optional[str] = None
    current_topic_title: Optional[str] = None
    overall_progress: float = 0.0  # 0.0 to 1.0
    overall_mastery: float = 0.0  # 0.0 to 1.0
    topics_completed: int = 0
    topics_remaining: int = 0
    streak_days: int = 0
    learning_minutes: int = 0
    weak_areas: List[str] = []
    next_action_title: str = "Start your journey"
    next_action_reason: str = "Begin your first foundational topic to establish baseline mastery."
    next_action_type: str = "LEARN"
    next_action_topic_id: Optional[str] = None
    revision_due_count: int = 0
    is_new_learner: bool = True
    insights: List[str] = []
    # Dynamic Schedule & Backlog Tracking
    target_deadline: Optional[date] = None
    days_remaining: int = 0
    schedule_status: str = "ON_TRACK"  # ON_TRACK, BEHIND_SCHEDULE, AHEAD_OF_SCHEDULE
    backlog_count: int = 0
    daily_instructions: Optional[str] = None
    today_target_topic_title: Optional[str] = None
    today_target_topic_id: Optional[str] = None
    today_key_concepts: List[str] = []
    today_estimated_minutes: int = 30
    daily_commitment_minutes: int = 30


class AreaMasteryItem(BaseModel):
    name: str
    mastery_score: float
    status: str


class TwinDashboardResponse(BaseModel):
    user_id: str
    has_sufficient_data: bool = False
    overall_mastery: float = 0.0  # 0.0 to 1.0
    learning_level: str = "Beginner"
    strongest_areas: List[AreaMasteryItem] = []
    weakest_areas: List[AreaMasteryItem] = []
    concepts_at_risk: List[str] = []
    learning_velocity: float = 0.0
    consistency_streak: int = 0
    knowledge_coverage: float = 0.0
    verified_evidence_count: int = 0
    insights: List[str] = []


# ---------------------------------------------------------------------------
# Contextual Q&A and Voice Schemas
# ---------------------------------------------------------------------------

class ContextualAskRequest(BaseModel):
    query: str
    topic_id: Optional[str] = None


class ContextualAskResponse(BaseModel):
    answer: str
    sources: List[str] = []
    suggested_followups: List[str] = []
    audio_tts_text: Optional[str] = None
