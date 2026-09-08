import uuid
import json
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from app.repositories.dynamic_learning_repository import DynamicLearningRepository, dynamic_learning_repo
from app.core.db_models import (
    GoalModel,
    LearningPathModel,
    LearningSectionModel,
    LearningTopicModel,
    LearnerTopicProgressModel,
)
from app.ai.providers.base import LLMProvider
from app.ai.providers.factory import get_llm_provider
from app.ai.prompts.v1 import learning_path as lp_prompt
from app.schemas.dynamic_learning import (
    LearningGoalCreateRequest,
    LearningGoalResponse,
    LearningPathResponse,
    LearningSectionResponse,
    LearningTopicResponse,
)
from app.core.exceptions import EntityNotFoundError, ValidationError
from app.core.logging import logger


class GeneratedTopicItem(BaseModel):
    title: str
    description: Optional[str] = None
    order_index: int = 1
    difficulty: str = "beginner"
    estimated_minutes: int = 25
    prerequisites: List[str] = Field(default_factory=list)
    learning_objectives: List[str] = Field(default_factory=list)
    status: str = "not_started"


class GeneratedSectionItem(BaseModel):
    title: str
    description: Optional[str] = None
    order_index: int = 1
    topics: List[GeneratedTopicItem] = Field(default_factory=list)


class GeneratedHierarchicalPath(BaseModel):
    title: str
    description: Optional[str] = None
    target_level: str = "Intermediate"
    estimated_duration: Optional[str] = "6-8 weeks"
    sections: List[GeneratedSectionItem] = Field(default_factory=list)


class LearningPathService:
    """
    Orchestration service for generating, validating, persisting,
    and retrieving personalized hierarchical learning paths.
    """

    def __init__(
        self,
        repo: DynamicLearningRepository = dynamic_learning_repo,
        llm_provider: Optional[LLMProvider] = None,
    ):
        self.repo = repo
        self._llm = llm_provider

    @property
    def llm(self) -> LLMProvider:
        if self._llm is None:
            self._llm = get_llm_provider()
        return self._llm

    # ---------------------------------------------------------------------------
    # Onboarding & Goal Creation
    # ---------------------------------------------------------------------------

    async def create_goal_and_generate_path(
        self,
        user_id: str,
        request: LearningGoalCreateRequest,
    ) -> LearningGoalResponse:
        goal_text = request.learning_goal.strip()
        if not goal_text:
            raise ValidationError("Learning goal cannot be empty.")

        target_lvl = request.target_level.strip() or "Intermediate"
        custom_tgt = request.custom_target.strip() if request.custom_target else None

        # 1. Persist Goal in Database
        goal_id = str(uuid.uuid4())
        goal = GoalModel(
            id=goal_id,
            user_id=user_id,
            title=goal_text,
            description=f"Goal: {goal_text} | Level: {target_lvl}" + (f" ({custom_tgt})" if custom_tgt else ""),
            deadline=None,
            current_level=target_lvl.lower(),
            target_level=target_lvl,
            custom_target=custom_tgt,
            existing_knowledge=", ".join(request.current_knowledge) if request.current_knowledge else None,
            constraints=[],
            daily_minutes=request.daily_minutes,
            status="ACTIVE",
            target_benchmark=custom_tgt or f"Achieve verified {target_lvl} mastery",
        )
        await self.repo.save_goal(goal)
        logger.info(f"Created goal {goal_id} for user {user_id}: '{goal_text}' ({target_lvl})")

        # 2. Generate and Persist Learning Path
        path = await self.generate_learning_path(
            user_id=user_id,
            goal_id=goal.id,
            learning_goal=goal_text,
            target_level=target_lvl,
            custom_target=custom_tgt,
            current_knowledge=request.current_knowledge,
            daily_minutes=request.daily_minutes,
            learning_preferences=request.learning_preferences,
            strengths=request.strengths,
            weaknesses=request.weaknesses,
        )

        return LearningGoalResponse(
            id=goal.id,
            user_id=goal.user_id,
            learning_goal=goal.title,
            target_level=goal.target_level,
            custom_target=goal.custom_target,
            daily_minutes=goal.daily_minutes,
            current_knowledge=request.current_knowledge,
            status=goal.status,
            active_path_id=path.id if path else None,
            progress=0.0,
            created_at=goal.created_at,
            updated_at=goal.updated_at,
        )

    # ---------------------------------------------------------------------------
    # Learning Path Generation Pipeline
    # ---------------------------------------------------------------------------

    async def generate_learning_path(
        self,
        user_id: str,
        goal_id: str,
        learning_goal: str,
        target_level: str,
        custom_target: Optional[str] = None,
        current_knowledge: Optional[List[str]] = None,
        daily_minutes: int = 30,
        learning_preferences: Optional[str] = None,
        strengths: Optional[str] = None,
        weaknesses: Optional[str] = None,
    ) -> LearningPathModel:
        # Check idempotency: Return existing active path if one already exists for this goal
        existing_path = await self.repo.get_path_by_goal_id(goal_id)
        if existing_path and existing_path.status == "ACTIVE":
            logger.info(f"Returning existing active path {existing_path.id} for goal {goal_id}")
            return existing_path

        # 1. Build prompt from versioned template
        prompt_str = lp_prompt.USER_PROMPT_TEMPLATE.format(
            learning_goal=learning_goal,
            target_level=target_level,
            custom_target=custom_target or "Comprehensive applied competence",
            current_knowledge=", ".join(current_knowledge) if current_knowledge else "None specified",
            available_time=f"{daily_minutes} minutes/day",
            learning_preferences=learning_preferences or "Practical, concept-first, project-oriented",
            strengths=strengths or "Motivated learner",
            weaknesses=weaknesses or "New to advanced architecture",
        )

        logger.info(f"Generating hierarchical learning path via prompt template {lp_prompt.VERSION} for goal: '{learning_goal}'")

        # 2. Invoke LLM with strict Structured Schema
        plan: Optional[GeneratedHierarchicalPath] = None
        try:
            plan = await self.llm.generate_structured(
                prompt=prompt_str,
                response_schema=GeneratedHierarchicalPath,
                system_prompt=lp_prompt.SYSTEM_PROMPT,
                temperature=0.2,
            )
        except Exception as e:
            logger.warning(f"LLM path generation failed: {e}. Generating curriculum via pedagogical generator.")

        if not plan or not plan.sections:
            plan = self._generate_fallback_curriculum(learning_goal, target_level, custom_target)

        # 3. Normalize & Persist to Database
        path_id = str(uuid.uuid4())
        path = LearningPathModel(
            id=path_id,
            goal_id=goal_id,
            user_id=user_id,
            title=plan.title or f"{learning_goal} Mastery Path",
            description=plan.description or f"Structured learning journey for {learning_goal}",
            target_level=target_level,
            estimated_duration=plan.estimated_duration or "8 weeks",
            version=1,
            status="ACTIVE",
            generation_status="READY",
            progress=0.0,
            metadata_json={"prompt_version": lp_prompt.VERSION},
        )
        await self.repo.save_path(path)

        section_models: List[LearningSectionModel] = []
        topic_models: List[LearningTopicModel] = []
        progress_models: List[LearnerTopicProgressModel] = []

        is_first_topic = True
        for s_idx, sec in enumerate(plan.sections):
            sec_id = str(uuid.uuid4())
            sec_model = LearningSectionModel(
                id=sec_id,
                path_id=path.id,
                title=sec.title,
                description=sec.description,
                order_index=s_idx + 1,
            )
            section_models.append(sec_model)

            for t_idx, top in enumerate(sec.topics):
                top_id = str(uuid.uuid4())
                top_model = LearningTopicModel(
                    id=top_id,
                    section_id=sec_id,
                    title=top.title,
                    description=top.description or top.title,
                    order_index=t_idx + 1,
                    difficulty=top.difficulty or "intermediate",
                    estimated_minutes=top.estimated_minutes or 25,
                    prerequisites=top.prerequisites or [],
                    learning_objectives=top.learning_objectives or [f"Understand and apply {top.title}"],
                )
                topic_models.append(top_model)

                # Initialize topic progress
                # First topic starts as "learning", others as "not_started"
                initial_status = "learning" if is_first_topic else "not_started"
                progress_model = LearnerTopicProgressModel(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    topic_id=top_id,
                    status=initial_status,
                    mastery_score=0.0,
                    confidence_score=0.0,
                    revision_count=0,
                    time_spent_minutes=0,
                    attempts=0,
                    started_at=datetime.now(timezone.utc) if is_first_topic else None,
                )
                progress_models.append(progress_model)
                is_first_topic = False

        # 1. First persist sections and topics so topic foreign keys exist in DB
        await self.repo.save_sections_and_topics(section_models, topic_models)
        logger.info(f"Persisted learning path {path_id} with {len(section_models)} sections and {len(topic_models)} topics.")

        # 2. Persist initial topic progress for all topics in batch
        await self.repo.save_multiple_topic_progress(progress_models)
        logger.info(f"Persisted initial progress for {len(progress_models)} topics.")
        return path

    # ---------------------------------------------------------------------------
    # Retrieval
    # ---------------------------------------------------------------------------

    async def get_active_path_response(self, user_id: str) -> Optional[LearningPathResponse]:
        path = await self.repo.get_active_path_for_user(user_id)
        if not path:
            return None
        return await self._build_path_response(path, user_id)

    async def get_path_by_id_response(self, path_id: str, user_id: str) -> LearningPathResponse:
        path = await self.repo.get_path_by_id(path_id)
        if not path:
            raise EntityNotFoundError("LearningPath", path_id)
        return await self._build_path_response(path, user_id)

    async def _build_path_response(self, path: LearningPathModel, user_id: str) -> LearningPathResponse:
        sections = await self.repo.get_sections_for_path(path.id)
        user_progress_list = await self.repo.list_progress_for_user(user_id)
        progress_map = {p.topic_id: p for p in user_progress_list}

        section_responses: List[LearningSectionResponse] = []
        total_topics = 0
        completed_topics = 0

        for sec in sections:
            topics = await self.repo.get_topics_for_section(sec.id)
            topic_responses: List[LearningTopicResponse] = []

            for top in topics:
                total_topics += 1
                prog = progress_map.get(top.id)
                status = prog.status if prog else "not_started"
                mastery = prog.mastery_score if prog else 0.0
                confidence = prog.confidence_score if prog else 0.0
                rev_count = prog.revision_count if prog else 0
                completed_at = prog.completed_at if prog else None
                next_rev = prog.next_revision_at if prog else None

                if status == "completed":
                    completed_topics += 1

                topic_responses.append(
                    LearningTopicResponse(
                        id=top.id,
                        section_id=top.section_id,
                        title=top.title,
                        description=top.description,
                        order_index=top.order_index,
                        difficulty=top.difficulty,
                        estimated_minutes=top.estimated_minutes,
                        prerequisites=top.prerequisites or [],
                        learning_objectives=top.learning_objectives or [],
                        status=status,
                        mastery_score=mastery,
                        confidence_score=confidence,
                        revision_count=rev_count,
                        completed_at=completed_at,
                        next_revision_at=next_rev,
                    )
                )

            section_responses.append(
                LearningSectionResponse(
                    id=sec.id,
                    path_id=sec.path_id,
                    title=sec.title,
                    description=sec.description,
                    order_index=sec.order_index,
                    topics=topic_responses,
                )
            )

        calc_progress = round(completed_topics / total_topics, 3) if total_topics > 0 else 0.0
        if path.progress != calc_progress:
            await self.repo.update_path_progress(path.id, calc_progress)
            path.progress = calc_progress

        return LearningPathResponse(
            id=path.id,
            goal_id=path.goal_id,
            user_id=path.user_id,
            title=path.title,
            description=path.description,
            target_level=path.target_level,
            estimated_duration=path.estimated_duration,
            version=path.version,
            status=path.status,
            generation_status=path.generation_status,
            generation_error=path.generation_error,
            progress=path.progress,
            sections=section_responses,
            created_at=path.created_at,
            updated_at=path.updated_at,
        )

    # ---------------------------------------------------------------------------
    # Fallback Generator (Deterministic, domain-adaptive)
    # ---------------------------------------------------------------------------

    def _generate_fallback_curriculum(
        self,
        goal: str,
        level: str,
        custom_target: Optional[str] = None,
    ) -> GeneratedHierarchicalPath:
        clean_goal = goal.strip()
        lvl = level.capitalize()
        is_interview = "interview" in lvl.lower() or (custom_target and "interview" in custom_target.lower())
        is_expert = "expert" in lvl.lower()

        sections = [
            GeneratedSectionItem(
                title=f"{clean_goal}: Core Foundations",
                description="Core primitives, architecture fundamentals, and design principles.",
                order_index=1,
                topics=[
                    GeneratedTopicItem(
                        title="Architecture & Request Lifecycle",
                        description=f"First principles, mental models, and request flow for {clean_goal}.",
                        order_index=1,
                        difficulty="beginner" if not is_expert else "intermediate",
                        estimated_minutes=25,
                        prerequisites=[],
                        learning_objectives=["Explain the execution lifecycle", "Map component boundaries"],
                    ),
                    GeneratedTopicItem(
                        title="Data Modeling & Schemas",
                        description="Data representation, field constraints, relationships, and validation.",
                        order_index=2,
                        difficulty="beginner" if not is_expert else "intermediate",
                        estimated_minutes=30,
                        prerequisites=["Architecture & Request Lifecycle"],
                        learning_objectives=["Define relational schemas", "Implement integrity constraints"],
                    ),
                    GeneratedTopicItem(
                        title="Business Logic & State Transitions",
                        description="Structuring service layers, handlers, and immutable state changes.",
                        order_index=3,
                        difficulty="intermediate",
                        estimated_minutes=30,
                        prerequisites=["Data Modeling & Schemas"],
                        learning_objectives=["Decouple business logic from controllers", "Handle error transitions"],
                    ),
                ],
            ),
            GeneratedSectionItem(
                title=f"{clean_goal}: Practical Implementation & APIs",
                description="Production API design, queries, validation, and integration tests.",
                order_index=2,
                topics=[
                    GeneratedTopicItem(
                        title="Query Optimization & Indexing",
                        description="N+1 queries, index selection, query plans, and memory footprint.",
                        order_index=1,
                        difficulty="intermediate",
                        estimated_minutes=35,
                        prerequisites=["Data Modeling & Schemas"],
                        learning_objectives=["Diagnose slow queries", "Design composite indexes"],
                    ),
                    GeneratedTopicItem(
                        title="Authentication & Authorization Policies",
                        description="Token lifecycle, role-based access, password hashing, and session hygiene.",
                        order_index=2,
                        difficulty="intermediate",
                        estimated_minutes=30,
                        prerequisites=["Business Logic & State Transitions"],
                        learning_objectives=["Implement secure auth workflows", "Enforce granular permissions"],
                    ),
                    GeneratedTopicItem(
                        title="Integration Testing & Error Contracts",
                        description="Automated API tests, transaction rollbacks, and structured failure modes.",
                        order_index=3,
                        difficulty="intermediate",
                        estimated_minutes=30,
                        prerequisites=["Authentication & Authorization Policies"],
                        learning_objectives=["Write reproducible integration tests", "Standardize API responses"],
                    ),
                ],
            ),
            GeneratedSectionItem(
                title=f"{clean_goal}: Scalability & Advanced Architecture",
                description="Caching strategies, asynchronous queues, resilience patterns, and observability.",
                order_index=3,
                topics=[
                    GeneratedTopicItem(
                        title="Caching & Invalidation Strategies",
                        description="Cache-aside, write-through, stampede protection, and eviction policies.",
                        order_index=1,
                        difficulty="advanced",
                        estimated_minutes=35,
                        prerequisites=["Query Optimization & Indexing"],
                        learning_objectives=["Implement cache layers", "Eliminate stale data hazards"],
                    ),
                    GeneratedTopicItem(
                        title="Background Workers & Asynchronous Tasks",
                        description="Message brokers, idempotent workers, dead-letter queues, and retries.",
                        order_index=2,
                        difficulty="advanced",
                        estimated_minutes=35,
                        prerequisites=["Caching & Invalidation Strategies"],
                        learning_objectives=["Offload slow work to asynchronous queues", "Ensure worker idempotency"],
                    ),
                    GeneratedTopicItem(
                        title="Observability & Performance Profiling",
                        description="Structured telemetry, metrics, distributed tracing, and bottleneck triage.",
                        order_index=3,
                        difficulty="advanced",
                        estimated_minutes=30,
                        prerequisites=["Background Workers & Asynchronous Tasks"],
                        learning_objectives=["Instrument critical paths", "Analyze runtime profiles"],
                    ),
                ],
            ),
        ]

        if is_interview or is_expert:
            sections.append(
                GeneratedSectionItem(
                    title=f"{clean_goal}: High-Scale System Design & Interview Proof",
                    description="Distributed trade-offs, fault tolerance, and technical interview execution.",
                    order_index=4,
                    topics=[
                        GeneratedTopicItem(
                            title="Distributed Data Consistency & Partitioning",
                            description="CAP theorem in practice, sharding schemes, replication, and failovers.",
                            order_index=1,
                            difficulty="expert",
                            estimated_minutes=45,
                            prerequisites=["Caching & Invalidation Strategies"],
                            learning_objectives=["Design horizontally partitioned systems", "Select consistency models"],
                        ),
                        GeneratedTopicItem(
                            title="Mock System Design Problem Execution",
                            description="Designing a large-scale real-time backend under interview constraints.",
                            order_index=2,
                            difficulty="expert",
                            estimated_minutes=45,
                            prerequisites=["Distributed Data Consistency & Partitioning"],
                            learning_objectives=["Articulate architecture tradeoffs", "Estimate resource requirements"],
                        ),
                    ],
                )
            )

        return GeneratedHierarchicalPath(
            title=f"{clean_goal} Mastery",
            description=f"Personalized path designed to take you to {lvl} competence in {clean_goal}.",
            target_level=lvl,
            estimated_duration="8-10 weeks",
            sections=sections,
        )


learning_path_service = LearningPathService()
