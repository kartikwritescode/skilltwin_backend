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
    Text,
    ForeignKey,
    JSON,
    Index,
)
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()


def utcnow():
    return datetime.now(timezone.utc)


class ProfileModel(Base):
    __tablename__ = "profiles"

    id = Column(String, primary_key=True)
    display_name = Column(String, nullable=True)
    email = Column(String, nullable=True)
    timezone = Column(String, default="UTC")
    daily_minutes = Column(Integer, default=30)
    preferences = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class GoalModel(Base):
    __tablename__ = "goals"

    id = Column(String, primary_key=True, default=lambda: f"goal_{uuid.uuid4().hex[:10]}")
    user_id = Column(String, ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    deadline = Column(String, nullable=True)
    current_level = Column(String, default="intermediate")
    existing_knowledge = Column(Text, nullable=True)
    constraints = Column(JSON, default=list)
    daily_minutes = Column(Integer, default=30)
    status = Column(String, default="ACTIVE", index=True)
    target_benchmark = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class JourneyModel(Base):
    __tablename__ = "journeys"

    id = Column(String, primary_key=True, default=lambda: f"jrn_{uuid.uuid4().hex[:10]}")
    goal_id = Column(String, ForeignKey("goals.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String, nullable=False, index=True)
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
