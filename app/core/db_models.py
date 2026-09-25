import uuid
from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy import (
    Column,
    String,
    Float,
    Integer,
    Boolean,
    DateTime,
    Date,
    Text,
    ForeignKey,
    JSON,
    Index,
    UniqueConstraint,
)
from sqlalchemy.types import TypeDecorator, CHAR
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, ENUM as PG_ENUM
from sqlalchemy.orm import relationship, declarative_base

class GUID(TypeDecorator):
    """Platform-independent GUID type.
    Uses PostgreSQL UUID type on postgresql dialect, CHAR(36) on sqlite.
    Returns native uuid.UUID for asyncpg bind params on PostgreSQL.
    """
    impl = CHAR(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == 'postgresql':
            # asyncpg requires native uuid.UUID objects for UUID columns
            if isinstance(value, uuid.UUID):
                return value
            try:
                return uuid.UUID(str(value))
            except (ValueError, AttributeError):
                return uuid.uuid5(uuid.NAMESPACE_DNS, str(value))
        else:
            # SQLite: store as string
            if isinstance(value, uuid.UUID):
                return str(value)
            try:
                return str(uuid.UUID(str(value)))
            except (ValueError, AttributeError):
                return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        return str(value)


class GoalStatusType(TypeDecorator):
    """Handles PostgreSQL custom enum goal_status and SQLite String."""
    impl = String
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(
                PG_ENUM(
                    "ACTIVE", "PAUSED", "COMPLETED", "ARCHIVED",
                    name="goal_status",
                    create_type=False,
                )
            )
        return dialect.type_descriptor(String())

    def process_bind_param(self, value, dialect):
        if value is None:
            return "ACTIVE"
        return str(value).upper()

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return str(value).upper()

Base = declarative_base()


def utcnow():
    return datetime.now(timezone.utc)


class ProfileModel(Base):
    __tablename__ = "profiles"

    id = Column(GUID(), primary_key=True)
    display_name = Column(String, nullable=True)
    email = Column(String, nullable=True)
    timezone = Column(String, default="UTC")
    daily_minutes = Column(Integer, default=30)
    preferences = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class GoalModel(Base):
    __tablename__ = "goals"

    id = Column(GUID(), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(GUID(), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    deadline = Column(Date, nullable=True)
    current_level = Column(String, default="intermediate")
    target_level = Column(String, default="Intermediate")
    custom_target = Column(String, nullable=True)
    existing_knowledge = Column(Text, nullable=True)
    constraints = Column(JSON, default=list)
    daily_minutes = Column(Integer, default=30)
    status = Column(GoalStatusType(), default="ACTIVE", index=True)
    target_benchmark = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class JourneyModel(Base):
    __tablename__ = "journeys"

    id = Column(GUID(), primary_key=True, default=lambda: str(uuid.uuid4()))
    goal_id = Column(GUID(), ForeignKey("goals.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(GUID(), nullable=False, index=True)
    title = Column(String, nullable=False)
    version = Column(Integer, default=1)
    status = Column(String, default="ACTIVE")
    generation_status = Column(String, default="PENDING")
    progress = Column(Float, default=0.0)
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class JourneyNodeModel(Base):
    __tablename__ = "journey_nodes"

    id = Column(String, primary_key=True, default=lambda: f"node_{uuid.uuid4().hex[:10]}")
    journey_id = Column(String, ForeignKey("journeys.id", ondelete="CASCADE"), nullable=False, index=True)
    concept_id = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False)
    subtitle = Column(Text, nullable=True)
    phase = Column(String, default="Core")
    order = Column(Integer, nullable=False)
    estimated_minutes = Column(Integer, default=20)
    state = Column(String, default="LOCKED")
    progress = Column(Float, default=0.0)
    prerequisites = Column(JSON, default=list)
    position_x = Column(Float, default=0.5)
    position_y = Column(Float, default=0.0)
    is_remediation = Column(Boolean, default=False)
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ConceptModel(Base):
    __tablename__ = "concepts"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False, index=True)
    description = Column(Text, nullable=True)
    domain = Column(String, default="Software Engineering")
    difficulty_level = Column(String, default="intermediate")
    prerequisites = Column(JSON, default=list)
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class ConceptEdgeModel(Base):
    __tablename__ = "concept_edges"

    id = Column(String, primary_key=True, default=lambda: f"edge_{uuid.uuid4().hex[:10]}")
    source_id = Column(String, ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False, index=True)
    target_id = Column(String, ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False, index=True)
    relationship_type = Column(String, default="prerequisite")
    weight = Column(Float, default=1.0)


class LearnerConceptModel(Base):
    __tablename__ = "learner_concepts"

    id = Column(String, primary_key=True, default=lambda: f"lc_{uuid.uuid4().hex[:10]}")
    user_id = Column(String, nullable=False, index=True)
    concept_id = Column(String, nullable=False, index=True)
    mastery_score = Column(Float, default=0.0)
    confidence_score = Column(Float, default=0.0)
    retention_score = Column(Float, default=100.0)
    risk_score = Column(Float, default=0.0)
    status = Column(String, default="NOT_STARTED")
    evidence_count = Column(Integer, default=0)
    misconception_tags = Column(JSON, default=list)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    next_review_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index("idx_learner_concepts_user_concept", "user_id", "concept_id", unique=True),
    )


class MisconceptionModel(Base):
    __tablename__ = "misconceptions"

    id = Column(String, primary_key=True, default=lambda: f"misc_{uuid.uuid4().hex[:10]}")
    user_id = Column(String, nullable=False, index=True)
    concept_id = Column(String, nullable=False, index=True)
    tag = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    severity = Column(String, default="medium")
    status = Column(String, default="active")
    detected_at = Column(DateTime(timezone=True), default=utcnow)
    resolved_at = Column(DateTime(timezone=True), nullable=True)


class SessionModel(Base):
    __tablename__ = "sessions"

    id = Column(String, primary_key=True, default=lambda: f"sess_{uuid.uuid4().hex[:10]}")
    user_id = Column(String, nullable=False, index=True)
    goal_id = Column(String, nullable=True)
    concept_id = Column(String, nullable=False, index=True)
    session_type = Column(String, nullable=False)
    status = Column(String, default="CREATED")
    score = Column(Float, nullable=True)
    confidence = Column(Float, nullable=True)
    steps = Column(JSON, default=list)
    result = Column(JSON, default=dict)
    started_at = Column(DateTime(timezone=True), default=utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class EvidenceModel(Base):
    __tablename__ = "evidence"

    id = Column(String, primary_key=True, default=lambda: f"evi_{uuid.uuid4().hex[:10]}")
    user_id = Column(String, nullable=False, index=True)
    concept_id = Column(String, nullable=False, index=True)
    session_id = Column(String, nullable=True)
    evidence_type = Column(String, nullable=False)
    score = Column(Float, nullable=False)
    feedback = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    reasoning_score = Column(Float, nullable=True)
    transfer_score = Column(Float, nullable=True)
    misconceptions_detected = Column(JSON, default=list)
    timestamp = Column(DateTime(timezone=True), default=utcnow)


class ResourceModel(Base):
    __tablename__ = "resources"

    id = Column(String, primary_key=True, default=lambda: f"res_{uuid.uuid4().hex[:10]}")
    user_id = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False)
    resource_type = Column(String, default="TEXT")
    storage_path = Column(String, nullable=True)
    source_url = Column(String, nullable=True)
    processing_status = Column(String, default="PROCESSING")
    is_public = Column(Boolean, default=False)
    extracted_concepts = Column(JSON, default=list)
    error_message = Column(Text, nullable=True)
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ResourceChunkModel(Base):
    __tablename__ = "resource_chunks"

    id = Column(String, primary_key=True, default=lambda: f"chk_{uuid.uuid4().hex[:10]}")
    resource_id = Column(String, ForeignKey("resources.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    concept_id = Column(String, nullable=True)
    embedding = Column(JSON, default=list)
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class MentorMessageModel(Base):
    __tablename__ = "mentor_messages"

    id = Column(String, primary_key=True, default=lambda: f"msg_{uuid.uuid4().hex[:10]}")
    user_id = Column(String, nullable=False, index=True)
    thread_id = Column(String, nullable=True, index=True)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class RecommendationModel(Base):
    __tablename__ = "recommendations"

    id = Column(String, primary_key=True, default=lambda: f"rec_{uuid.uuid4().hex[:10]}")
    user_id = Column(String, nullable=False, index=True)
    goal_id = Column(String, nullable=True)
    concept_id = Column(String, nullable=True)
    journey_node_id = Column(String, nullable=True)
    action_type = Column(String, nullable=False)
    title = Column(String, nullable=False)
    reason = Column(Text, nullable=True)
    priority = Column(Float, default=1.0)
    estimated_minutes = Column(Integer, default=20)
    quick_action_label = Column(String, default="Start")
    status = Column(String, default="PENDING")
    created_at = Column(DateTime(timezone=True), default=utcnow)


class ReviewItemModel(Base):
    __tablename__ = "review_items"

    id = Column(String, primary_key=True, default=lambda: f"rev_{uuid.uuid4().hex[:10]}")
    user_id = Column(String, nullable=False, index=True)
    concept_id = Column(String, nullable=False, index=True)
    concept_name = Column(String, nullable=False)
    due_at = Column(DateTime(timezone=True), nullable=False)
    interval_days = Column(Integer, default=1)
    retention_score = Column(Float, default=50.0)
    retention_risk = Column(String, default="low")
    successful_retrievals = Column(Integer, default=0)
    failed_retrievals = Column(Integer, default=0)
    is_high_priority = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index("idx_review_items_user_concept", "user_id", "concept_id", unique=True),
    )


# =========================================================
# DYNAMIC LEARNING SYSTEM MODELS (HIERARCHICAL & ADAPTIVE)
# =========================================================

class LearningGoalModel(Base):
    __tablename__ = "learning_goals"

    id = Column(GUID(), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(GUID(), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    learning_goal = Column(Text, nullable=False)
    target_level = Column(String, default="Intermediate")
    custom_target = Column(Text, nullable=True)
    daily_minutes = Column(Integer, default=30)
    current_knowledge = Column(JSON, default=list)
    status = Column(String, default="ACTIVE", index=True)
    metadata_json = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class LearningPathModel(Base):
    __tablename__ = "learning_paths"

    id = Column(GUID(), primary_key=True, default=lambda: str(uuid.uuid4()))
    goal_id = Column(GUID(), ForeignKey("learning_goals.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(GUID(), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    target_level = Column(String, default="Intermediate")
    estimated_duration = Column(String, nullable=True)
    version = Column(Integer, default=1)
    status = Column(String, default="ACTIVE")
    generation_status = Column(String, default="READY")  # PENDING, PROCESSING, READY, FAILED
    generation_error = Column(Text, nullable=True)
    progress = Column(Float, default=0.0)
    metadata_json = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class LearningSectionModel(Base):
    __tablename__ = "learning_sections"

    id = Column(GUID(), primary_key=True, default=lambda: str(uuid.uuid4()))
    path_id = Column(GUID(), ForeignKey("learning_paths.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    order_index = Column(Integer, nullable=False)
    metadata_json = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class LearningTopicModel(Base):
    __tablename__ = "learning_topics"

    id = Column(GUID(), primary_key=True, default=lambda: str(uuid.uuid4()))
    section_id = Column(GUID(), ForeignKey("learning_sections.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    order_index = Column(Integer, nullable=False)
    difficulty = Column(String, default="beginner")  # beginner, intermediate, advanced, expert
    estimated_minutes = Column(Integer, default=25)
    prerequisites = Column(JSON, default=list)
    learning_objectives = Column(JSON, default=list)
    metadata_json = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class TopicDependencyModel(Base):
    __tablename__ = "topic_dependencies"

    id = Column(GUID(), primary_key=True, default=lambda: str(uuid.uuid4()))
    source_topic_id = Column(GUID(), ForeignKey("learning_topics.id", ondelete="CASCADE"), nullable=False, index=True)
    target_topic_id = Column(GUID(), ForeignKey("learning_topics.id", ondelete="CASCADE"), nullable=False, index=True)
    dependency_type = Column(String, default="prerequisite")


class LearnerTopicProgressModel(Base):
    __tablename__ = "learner_topic_progress"

    id = Column(GUID(), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(GUID(), nullable=False, index=True)
    topic_id = Column(GUID(), ForeignKey("learning_topics.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String, default="not_started")  # not_started, learning, completed, needs_revision
    mastery_score = Column(Float, default=0.0)
    confidence_score = Column(Float, default=0.0)
    revision_count = Column(Integer, default=0)
    time_spent_minutes = Column(Integer, default=0)
    attempts = Column(Integer, default=0)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    last_accessed_at = Column(DateTime(timezone=True), default=utcnow)
    next_revision_at = Column(DateTime(timezone=True), nullable=True)
    metadata_json = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        Index("idx_learner_topic_user_topic", "user_id", "topic_id", unique=True),
    )


class TopicQuestionModel(Base):
    __tablename__ = "topic_questions"

    id = Column(GUID(), primary_key=True, default=lambda: str(uuid.uuid4()))
    topic_id = Column(GUID(), ForeignKey("learning_topics.id", ondelete="CASCADE"), nullable=False, index=True)
    question_type = Column(String, default="mcq")  # mcq, true_false, short_answer, scenario, code_fix, interview
    prompt = Column(Text, nullable=False)
    options = Column(JSON, default=list)
    correct_answer = Column(Text, nullable=False)
    explanation = Column(Text, nullable=False)
    difficulty = Column(String, default="medium")
    metadata_json = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class QuestionAttemptModel(Base):
    __tablename__ = "question_attempts"

    id = Column(GUID(), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(GUID(), nullable=False, index=True)
    question_id = Column(GUID(), ForeignKey("topic_questions.id", ondelete="CASCADE"), nullable=False, index=True)
    topic_id = Column(GUID(), nullable=False, index=True)
    user_answer = Column(Text, nullable=False)
    is_correct = Column(Boolean, nullable=False)
    score = Column(Float, default=0.0)
    feedback = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)


class TopicExplanationCacheModel(Base):
    __tablename__ = "topic_explanations_cache"

    id = Column(GUID(), primary_key=True, default=lambda: str(uuid.uuid4()))
    topic_id = Column(GUID(), ForeignKey("learning_topics.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(GUID(), nullable=False, index=True)
    content = Column(Text, nullable=False)
    prompt_version = Column(String, default="v1")
    created_at = Column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("idx_topic_explanation_cache", "topic_id", "user_id", "prompt_version", unique=True),
    )


class TwinMetricsModel(Base):
    __tablename__ = "twin_metrics"

    id = Column(GUID(), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(GUID(), nullable=False, unique=True, index=True)
    overall_mastery = Column(Float, default=0.0)
    current_level = Column(String, default="Beginner")
    strongest_areas = Column(JSON, default=list)
    weakest_areas = Column(JSON, default=list)
    concepts_at_risk = Column(JSON, default=list)
    learning_velocity = Column(Float, default=0.0)
    consistency_streak = Column(Integer, default=0)
    knowledge_coverage = Column(Float, default=0.0)
    has_sufficient_data = Column(Boolean, default=False)
    insights = Column(JSON, default=list)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class CanonicalRoadmapModel(Base):
    __tablename__ = "canonical_roadmaps"

    id = Column(String, primary_key=True)  # e.g. "roadmap_flutter_mobile"
    slug = Column(String, nullable=False, unique=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    domain = Column(String, default="Software Engineering", index=True)
    target_role = Column(String, nullable=True)
    difficulty_baseline = Column(String, default="Beginner")
    tags = Column(JSON, default=list)  # list of keywords/aliases
    embedding = Column(JSON, default=list)  # 768-dim list of floats (text-embedding-004)
    total_nodes = Column(Integer, default=0)
    estimated_hours = Column(Float, default=0.0)
    is_active = Column(Boolean, default=True)
    version = Column(Integer, default=1)
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    nodes = relationship("CanonicalNodeModel", back_populates="roadmap", cascade="all, delete-orphan", order_by="CanonicalNodeModel.order")


class CanonicalNodeModel(Base):
    __tablename__ = "canonical_nodes"

    id = Column(String, primary_key=True)  # e.g. "cnode_flutter_widget_tree"
    roadmap_id = Column(String, ForeignKey("canonical_roadmaps.id", ondelete="CASCADE"), nullable=False, index=True)
    concept_id = Column(String, nullable=False, index=True)
    title = Column(String, nullable=False)
    subtitle = Column(Text, nullable=True)
    phase = Column(String, default="Core")  # Foundations, Core, Practice, Advanced, Mastery
    tier = Column(String, default="intermediate")  # foundation, intermediate, advanced
    importance = Column(String, default="essential")  # essential, recommended, advanced, niche
    difficulty = Column(String, default="intermediate")  # beginner, intermediate, advanced, expert
    order = Column(Integer, nullable=False)
    estimated_minutes = Column(Integer, default=25)
    prerequisites = Column(JSON, default=list)  # list of concept_ids or node_ids
    learning_objectives = Column(JSON, default=list)
    feynman_prompts = Column(JSON, default=list)
    key_misconceptions = Column(JSON, default=list)
    recommended_resources = Column(JSON, default=list)
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    roadmap = relationship("CanonicalRoadmapModel", back_populates="nodes")


# =========================================================
# YOUTUBE PLAYLIST & ROADMAP PERSISTENCE MODELS
# =========================================================

class YouTubePlaylistModel(Base):
    __tablename__ = "youtube_playlists"

    id = Column(GUID(), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(GUID(), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    youtube_playlist_id = Column(String(128), nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    channel_name = Column(String, nullable=True)
    thumbnail_url = Column(String, nullable=True)
    video_count = Column(Integer, default=0)
    total_duration_seconds = Column(Integer, default=0)
    content_hash = Column(String(64), nullable=False, index=True)
    analysis_status = Column(String(32), default="READY")  # QUEUED, FETCHING, ANALYZING, GENERATING_ROADMAP, READY, FAILED
    analysis_version = Column(Integer, default=1)
    learning_path_id = Column(GUID(), ForeignKey("learning_paths.id", ondelete="SET NULL"), nullable=True, index=True)
    metadata_json = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    videos = relationship("YouTubePlaylistVideoModel", back_populates="playlist", cascade="all, delete-orphan", order_by="YouTubePlaylistVideoModel.position")


class YouTubePlaylistVideoModel(Base):
    __tablename__ = "youtube_playlist_videos"

    id = Column(GUID(), primary_key=True, default=lambda: str(uuid.uuid4()))
    playlist_id = Column(GUID(), ForeignKey("youtube_playlists.id", ondelete="CASCADE"), nullable=False, index=True)
    youtube_video_id = Column(String(64), nullable=False, index=True)
    position = Column(Integer, nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    duration_seconds = Column(Integer, default=0)
    thumbnail_url = Column(String, nullable=True)
    youtube_url = Column(String, nullable=False)
    topic = Column(String, nullable=True)
    subtopics = Column(JSON, default=list)
    difficulty = Column(String(32), default="beginner")
    concepts = Column(JSON, default=list)
    prerequisite_positions = Column(JSON, default=list)
    status = Column(String(32), default="NOT_STARTED")  # NOT_STARTED, IN_PROGRESS, COMPLETED, SKIPPED
    availability = Column(String(32), default="available")  # available, unavailable, private, deleted
    notes = Column(Text, nullable=True)
    watch_progress = Column(Float, default=0.0)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    user_rating = Column(Float, nullable=True)
    metadata_json = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    playlist = relationship("YouTubePlaylistModel", back_populates="videos")

    __table_args__ = (
        UniqueConstraint("playlist_id", "youtube_video_id", name="uq_youtube_playlist_video"),
        UniqueConstraint("playlist_id", "position", name="uq_youtube_playlist_position"),
    )


class YouTubePlaylistCacheModel(Base):
    __tablename__ = "youtube_playlist_cache"

    id = Column(String, primary_key=True)  # e.g. cache_{playlist_id}_{content_hash}
    youtube_playlist_id = Column(String(128), nullable=False, index=True)
    content_hash = Column(String(64), nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    channel_name = Column(String, nullable=True)
    thumbnail_url = Column(String, nullable=True)
    video_count = Column(Integer, default=0)
    total_duration_seconds = Column(Integer, default=0)
    cached_videos = Column(JSON, default=list)
    topic_groups = Column(JSON, default=list)
    analysis_version = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("youtube_playlist_id", "content_hash", name="uq_youtube_cache_playlist_hash"),
    )


# ============================================================================
# Adaptive Directed Acyclic Graph (ADAG) Engine Models
# ============================================================================

class CanonicalOntologyModel(Base):
    __tablename__ = "canonical_ontologies"

    id = Column(String(64), primary_key=True)  # e.g., ontology_web_development
    domain = Column(String(64), nullable=False, index=True)
    title = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    embedding = Column(JSON, nullable=True)  # Vector embedding stored as JSON array for cross-platform compatibility
    total_nodes = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    subgraphs = relationship("MicroSubgraphModel", back_populates="ontology", cascade="all, delete-orphan")


class MicroSubgraphModel(Base):
    __tablename__ = "micro_subgraphs"

    id = Column(String(64), primary_key=True)  # e.g., subgraph_jwt_auth
    ontology_id = Column(String(64), ForeignKey("canonical_ontologies.id", ondelete="CASCADE"), nullable=True, index=True)
    slug = Column(String(64), unique=True, index=True, nullable=False)
    title = Column(String(128), nullable=False)
    tier = Column(String(32), default="core")  # foundational, core, advanced, elective
    estimated_minutes = Column(Integer, default=60)
    prerequisites = Column(JSON, default=list)  # array of micro_subgraph slugs
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    ontology = relationship("CanonicalOntologyModel", back_populates="subgraphs")


class AdaptiveLearningPathModel(Base):
    __tablename__ = "adaptive_learning_paths"

    id = Column(GUID(), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(GUID(), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    goal_id = Column(GUID(), ForeignKey("goals.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(128), nullable=False)
    status = Column(String(32), default="ACTIVE")  # ACTIVE, COMPLETED, PAUSED, ARCHIVED
    target_deadline = Column(Date, nullable=True)
    daily_budget_minutes = Column(Integer, default=30)
    velocity_factor = Column(Float, default=1.0)
    path_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    nodes = relationship("PathNodeModel", back_populates="path", cascade="all, delete-orphan", order_by="PathNodeModel.order_index")
    edges = relationship("PathNodeEdgeModel", back_populates="path", cascade="all, delete-orphan")


class PathNodeModel(Base):
    __tablename__ = "path_nodes"

    id = Column(String(64), primary_key=True)  # UUID string or deterministic composite slug
    path_id = Column(GUID(), ForeignKey("adaptive_learning_paths.id", ondelete="CASCADE"), nullable=False, index=True)
    subgraph_id = Column(String(64), nullable=True, index=True)
    concept_id = Column(String(64), nullable=False, index=True)
    title = Column(String(128), nullable=False)
    state = Column(String(32), default="LOCKED")  # LOCKED, AVAILABLE, CURRENT, COMPLETED, NEEDS_REVISION, REMEDIATING, BYPASSED
    order_index = Column(Integer, nullable=False, index=True)
    is_remediation = Column(Boolean, default=False)
    spliced_after_node_id = Column(String(64), nullable=True)
    is_elaborated = Column(Boolean, default=False)
    mastery_score = Column(Float, default=0.0)
    time_spent_minutes = Column(Integer, default=0)
    node_metadata = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    path = relationship("AdaptiveLearningPathModel", back_populates="nodes")
    outgoing_edges = relationship(
        "PathNodeEdgeModel",
        foreign_keys="PathNodeEdgeModel.source_node_id",
        back_populates="source_node",
        cascade="all, delete-orphan",
    )
    incoming_edges = relationship(
        "PathNodeEdgeModel",
        foreign_keys="PathNodeEdgeModel.target_node_id",
        back_populates="target_node",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("path_id", "concept_id", name="uq_path_concept"),
    )


class PathNodeEdgeModel(Base):
    __tablename__ = "path_node_edges"

    id = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    path_id = Column(GUID(), ForeignKey("adaptive_learning_paths.id", ondelete="CASCADE"), nullable=False, index=True)
    source_node_id = Column(String(64), ForeignKey("path_nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    target_node_id = Column(String(64), ForeignKey("path_nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    edge_type = Column(String(32), default="prerequisite")  # prerequisite, remediation_detour, recommendation
    created_at = Column(DateTime(timezone=True), default=utcnow)

    path = relationship("AdaptiveLearningPathModel", back_populates="edges")
    source_node = relationship("PathNodeModel", foreign_keys=[source_node_id], back_populates="outgoing_edges")
    target_node = relationship("PathNodeModel", foreign_keys=[target_node_id], back_populates="incoming_edges")

    __table_args__ = (
        UniqueConstraint("path_id", "source_node_id", "target_node_id", name="uq_path_edge"),
    )


class ElaboratedTopicCacheModel(Base):
    __tablename__ = "elaborated_topic_cache"

    concept_id = Column(String(64), primary_key=True)
    difficulty = Column(String(32), default="intermediate")
    explanation_markdown = Column(Text, nullable=False)
    key_invariants = Column(JSON, default=list)
    practice_questions = Column(JSON, default=list)
    code_challenges = Column(JSON, default=list)
    prompt_version = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


