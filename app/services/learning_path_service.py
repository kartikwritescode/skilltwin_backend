import uuid
import json
from datetime import datetime, timezone, date
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
    key_concepts: List[str] = Field(default_factory=list)
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
            deadline=request.deadline,
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
        logger.info(f"Created goal {goal_id} for user {user_id}: '{goal_text}' ({target_lvl}, deadline: {request.deadline})")

        # 2. Generate and Persist Learning Path
        path = await self.generate_learning_path(
            user_id=user_id,
            goal_id=goal.id,
            learning_goal=goal_text,
            target_level=target_lvl,
            custom_target=custom_tgt,
            deadline=request.deadline,
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
            deadline=goal.deadline,
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
        deadline: Optional[date] = None,
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

        # Calculate deadline pacing & total study capacity
        days_until_deadline = 60
        deadline_str = "Flexible (approx. 8-10 weeks)"
        if deadline:
            today = datetime.now(timezone.utc).date()
            diff_days = (deadline - today).days
            if diff_days > 0:
                days_until_deadline = diff_days
                deadline_str = f"{deadline.strftime('%b %d, %Y')} ({diff_days} days remaining)"

        total_capacity_hours = round((days_until_deadline * daily_minutes) / 60.0, 1)

        # 1. Build prompt from versioned template
        prompt_str = lp_prompt.USER_PROMPT_TEMPLATE.format(
            learning_goal=learning_goal,
            target_level=target_level,
            custom_target=custom_target or "Comprehensive applied competence",
            target_deadline=deadline_str,
            available_time=f"{daily_minutes} minutes/day",
            total_capacity_hours=f"{total_capacity_hours} hours total",
            current_knowledge=", ".join(current_knowledge) if current_knowledge else "None specified",
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
            estimated_duration=plan.estimated_duration or f"{max(2, days_until_deadline // 7)} weeks",
            version=2,
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
                    metadata_json={"key_concepts": top.key_concepts or []},
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

                top_meta = top.metadata_json if hasattr(top, "metadata_json") and isinstance(top.metadata_json, dict) else {}
                key_concepts = top_meta.get("key_concepts", [])

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
                        key_concepts=key_concepts,
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
        is_expert = lvl == "Expert"
        is_fullstack = "full stack" in clean_goal.lower() or "fullstack" in clean_goal.lower() or "web" in clean_goal.lower()

        if is_fullstack:
            sections = [
                GeneratedSectionItem(
                    title="1. Web Foundations & Modern JavaScript/TypeScript",
                    description="Execution contexts, DOM mechanics, modern asynchronous paradigms, and type contracts.",
                    order_index=1,
                    topics=[
                        GeneratedTopicItem(
                            title="Event Loop, Microtasks & Asynchronous Runtimes",
                            description="Deep mental models of call stacks, event loops, promises, and concurrency in browser and Node runtimes.",
                            order_index=1,
                            difficulty="beginner" if not is_expert else "intermediate",
                            estimated_minutes=30,
                            prerequisites=[],
                            learning_objectives=["Trace microtask vs macrotask execution order", "Prevent thread-blocking synchronous traps"],
                            key_concepts=["Call Stack Execution", "Microtask Queue (Promises)", "Macrotask Queue (Timers/I/O)", "Event Loop Ticks", "async/await Sugar", "Thread Pool Offloading"],
                        ),
                        GeneratedTopicItem(
                            title="TypeScript Type Systems & Generic Contracts",
                            description="Structural typing, generics, utility types, discriminating unions, and strict null safety.",
                            order_index=2,
                            difficulty="intermediate",
                            estimated_minutes=35,
                            prerequisites=["Event Loop, Microtasks & Asynchronous Runtimes"],
                            learning_objectives=["Define compile-time type invariants", "Refactor JavaScript modules to strict TypeScript"],
                            key_concepts=["Structural Subtyping", "Discriminated Unions", "Generics & Constraints", "Mapped & Conditional Types", "Strict Null Checks", "Type Narrowing"],
                        ),
                        GeneratedTopicItem(
                            title="DOM Rendering Pipeline & Browser Performance",
                            description="Reflows, repaints, composite layers, virtual DOM trade-offs, and critical rendering path optimization.",
                            order_index=3,
                            difficulty="intermediate",
                            estimated_minutes=30,
                            prerequisites=["TypeScript Type Systems & Generic Contracts"],
                            learning_objectives=["Profile browser frame rates and layouts", "Minimize unneeded layout thrashing"],
                            key_concepts=["Critical Rendering Path", "Reflow vs Repaint", "GPU Layer Compositing", "Layout Thrashing", "Virtual DOM Reconciliation", "requestAnimationFrame"],
                        ),
                        GeneratedTopicItem(
                            title="Modern Package Management & Build Toolchains",
                            description="Bundlers (Vite/Rollup), tree-shaking, code splitting, environment variables, and module resolution.",
                            order_index=4,
                            difficulty="intermediate",
                            estimated_minutes=25,
                            prerequisites=["DOM Rendering Pipeline & Browser Performance"],
                            learning_objectives=["Configure high-performance modern build pipelines", "Analyze production bundle sizes"],
                            key_concepts=["ES Modules vs CommonJS", "Tree-Shaking Algorithms", "Rollup/Vite Chunker", "Dynamic Imports", "Source Maps", "Bundle Budget Analysis"],
                        ),
                    ],
                ),
                GeneratedSectionItem(
                    title="2. Frontend Architecture, UI State & Component Systems",
                    description="Component lifecycles, unidirectional data flow, reactive state management, and design systems.",
                    order_index=2,
                    topics=[
                        GeneratedTopicItem(
                            title="Component Lifecycles & Reactive State Machines",
                            description="Declarative UI hierarchies, reconciliation algorithms, controlled vs uncontrolled state, and pure renderers.",
                            order_index=1,
                            difficulty="intermediate",
                            estimated_minutes=35,
                            prerequisites=["DOM Rendering Pipeline & Browser Performance"],
                            learning_objectives=["Build predictable component hierarchies", "Eliminate unintended side-effects"],
                            key_concepts=["Virtual DOM Diffing", "Component Mount/Unmount/Update", "Reactive Signals / Hooks", "Pure Render Functions", "State Colocation", "Derived State"],
                        ),
                        GeneratedTopicItem(
                            title="Global State Management & Cache Hydration",
                            description="Single source of truth, normalized stores, optimistic client updates, and async server state synchronization.",
                            order_index=2,
                            difficulty="intermediate",
                            estimated_minutes=40,
                            prerequisites=["Component Lifecycles & Reactive State Machines"],
                            learning_objectives=["Implement normalized global state stores", "Synchronize remote entity caches"],
                            key_concepts=["Single Source of Truth", "Normalized Entity Tables", "Optimistic Mutations", "Stale-While-Revalidate", "Cache Invalidation", "Hydration Mismatches"],
                        ),
                        GeneratedTopicItem(
                            title="Design Systems, Accessibility & Responsive Layouts",
                            description="Modern CSS Grid, Flexbox, ARIA landmarks, keyboard navigation, and theme tokens.",
                            order_index=3,
                            difficulty="intermediate",
                            estimated_minutes=30,
                            prerequisites=["Component Lifecycles & Reactive State Machines"],
                            learning_objectives=["Construct fluid responsive interfaces", "Ensure WCAG 2.1 AA accessibility compliance"],
                            key_concepts=["CSS Grid & Flexbox Mechanics", "Design Tokens & Themes", "WCAG 2.1 AA Contrast Ratios", "Screen Reader ARIA Roles", "Keyboard Focus Trapping", "Fluid Typography"],
                        ),
                        GeneratedTopicItem(
                            title="Client-Side Routing & Dynamic Code Splitting",
                            description="Single page application (SPA) routing, route guards, nested layouts, and pre-fetching critical chunks.",
                            order_index=4,
                            difficulty="intermediate",
                            estimated_minutes=30,
                            prerequisites=["Global State Management & Cache Hydration"],
                            learning_objectives=["Implement protected navigation hierarchies", "Configure lazy-loaded route boundaries"],
                            key_concepts=["HTML5 History API", "Protected Route Guards", "Nested Layout Outlets", "Dynamic Import Boundaries", "Pre-fetching Strategies", "Route Error Boundaries"],
                        ),
                    ],
                ),
                GeneratedSectionItem(
                    title="3. Backend Engineering, Protocols & API Architectures",
                    description="HTTP specification, RESTful contracts, GraphQL/gRPC, middleware pipelines, and controller-service decoupling.",
                    order_index=3,
                    topics=[
                        GeneratedTopicItem(
                            title="HTTP Protocols, Headers & Request Lifecycle",
                            description="HTTP/1.1 vs HTTP/2 vs HTTP/3, TLS handshakes, status semantics, caching headers, and idempotency keys.",
                            order_index=1,
                            difficulty="intermediate",
                            estimated_minutes=30,
                            prerequisites=[],
                            learning_objectives=["Design idempotent REST endpoints", "Leverage HTTP caching and ETag headers"],
                            key_concepts=["TCP vs QUIC/UDP Runtimes", "TLS 1.3 Handshake Mechanics", "Idempotency Keys", "ETag & Conditional Requests", "HTTP Status Semantics", "Multiplexed Streams"],
                        ),
                        GeneratedTopicItem(
                            title="Layered Service Architecture & Middleware Pipelines",
                            description="Separation of concerns across controllers, domain services, validation middleware, and repositories.",
                            order_index=2,
                            difficulty="intermediate",
                            estimated_minutes=35,
                            prerequisites=["HTTP Protocols, Headers & Request Lifecycle"],
                            learning_objectives=["Structure decoupled enterprise backend services", "Intercept requests with validation middleware"],
                            key_concepts=["Controller-Service-Repository Pattern", "Request Interceptor Chains", "Dependency Injection Containers", "Context Propagation", "Domain Logic Isolation", "Cross-Cutting Concerns"],
                        ),
                        GeneratedTopicItem(
                            title="Data Validation, Serialization & Error Contracts",
                            description="Schema parsing, input sanitization, RFC 7807 problem details, and standardized JSON error contracts.",
                            order_index=3,
                            difficulty="intermediate",
                            estimated_minutes=30,
                            prerequisites=["Layered Service Architecture & Middleware Pipelines"],
                            learning_objectives=["Enforce strict input validation boundaries", "Return predictable structured error payloads"],
                            key_concepts=["Schema Invariants Parsing", "Input Sanitization & Escaping", "RFC 7807 Problem Details", "Serialization Overheads", "Custom Error Hierarchies", "Fail-Fast Validation"],
                        ),
                        GeneratedTopicItem(
                            title="File Streaming, Multipart Uploads & Cloud Storage",
                            description="Streaming large payloads, presigned upload URLs, chunked transfer, and storage buckets.",
                            order_index=4,
                            difficulty="intermediate",
                            estimated_minutes=35,
                            prerequisites=["Layered Service Architecture & Middleware Pipelines"],
                            learning_objectives=["Stream file uploads without memory leaks", "Issue secure presigned cloud upload URLs"],
                            key_concepts=["Multipart MIME Encodings", "Stream Backpressure Buffering", "Presigned S3/GCS Upload URLs", "Chunked Transfer Encoding", "Temporary Memory Spilling", "Virus/Payload Validation"],
                        ),
                    ],
                ),
                GeneratedSectionItem(
                    title="4. Databases, Schemas & Query Performance",
                    description="Relational data modeling, indexes, ACID transactions, connection pools, and NoSQL trade-offs.",
                    order_index=4,
                    topics=[
                        GeneratedTopicItem(
                            title="Relational Schema Normalization & Foreign Keys",
                            description="1NF to 3NF, table constraints, composite primary keys, cascade rules, and relational invariants.",
                            order_index=1,
                            difficulty="intermediate",
                            estimated_minutes=35,
                            prerequisites=["Layered Service Architecture & Middleware Pipelines"],
                            learning_objectives=["Design robust multi-table schemas", "Enforce referential integrity at the database layer"],
                        ),
                        GeneratedTopicItem(
                            title="Database Indexing, B-Trees & Query Optimization",
                            description="EXPLAIN ANALYZE, B-tree mechanics, covering indexes, sequential scan elimination, and N+1 query prevention.",
                            order_index=2,
                            difficulty="advanced",
                            estimated_minutes=40,
                            prerequisites=["Relational Schema Normalization & Foreign Keys"],
                            learning_objectives=["Diagnose slow queries using query execution plans", "Construct targeted composite indexes"],
                        ),
                        GeneratedTopicItem(
                            title="ACID Transactions & Concurrency Isolation Levels",
                            description="Dirty reads, phantom reads, Read Committed vs Serializable, row-level locking, and deadlocks.",
                            order_index=3,
                            difficulty="advanced",
                            estimated_minutes=35,
                            prerequisites=["Database Indexing, B-Trees & Query Optimization"],
                            learning_objectives=["Handle financial and inventory transactional mutations", "Prevent race conditions and deadlocks"],
                        ),
                        GeneratedTopicItem(
                            title="Database Migrations & Connection Pool Tuning",
                            description="Zero-downtime migration strategies (expand/contract), connection exhaustion, PgBouncer, and health pooling.",
                            order_index=4,
                            difficulty="advanced",
                            estimated_minutes=30,
                            prerequisites=["ACID Transactions & Concurrency Isolation Levels"],
                            learning_objectives=["Execute backward-compatible schema migrations", "Tune pool sizes for production traffic spikes"],
                        ),
                    ],
                ),
                GeneratedSectionItem(
                    title="5. Authentication, Security & Threat Defenses",
                    description="Identity management, tokens, session storage, OAuth2 flows, and OWASP Top 10 vulnerabilities.",
                    order_index=5,
                    topics=[
                        GeneratedTopicItem(
                            title="Password Hashing, Salting & JWT Lifecycle",
                            description="Argon2/bcrypt hashing algorithms, access vs refresh tokens, token revocation, and secure HTTP-only cookies.",
                            order_index=1,
                            difficulty="intermediate",
                            estimated_minutes=35,
                            prerequisites=["HTTP Protocols, Headers & Request Lifecycle"],
                            learning_objectives=["Implement secure token authentication", "Mitigate token theft vectors"],
                        ),
                        GeneratedTopicItem(
                            title="Role-Based Access Control (RBAC) & Permissions",
                            description="Hierarchical permissions, attribute-based access control, policy enforcement, and route middleware.",
                            order_index=2,
                            difficulty="intermediate",
                            estimated_minutes=30,
                            prerequisites=["Password Hashing, Salting & JWT Lifecycle"],
                            learning_objectives=["Implement granular permission enforcement", "Prevent privilege escalation exploits"],
                        ),
                        GeneratedTopicItem(
                            title="OWASP Top 10 Defenses (XSS, CSRF, SQLi & CORS)",
                            description="Content Security Policy (CSP), parameterized queries, SameSite cookie attributes, and CORS headers.",
                            order_index=3,
                            difficulty="advanced",
                            estimated_minutes=40,
                            prerequisites=["Role-Based Access Control (RBAC) & Permissions"],
                            learning_objectives=["Audit endpoints against common web vulnerabilities", "Configure strict CORS and security headers"],
                        ),
                        GeneratedTopicItem(
                            title="Rate Limiting, Throttling & DDoS Protection",
                            description="Token bucket and leaky bucket algorithms, IP rate-limiting with Redis, and API abuse prevention.",
                            order_index=4,
                            difficulty="advanced",
                            estimated_minutes=30,
                            prerequisites=["OWASP Top 10 Defenses (XSS, CSRF, SQLi & CORS)"],
                            learning_objectives=["Protect authentication endpoints with distributed rate limiting", "Implement sliding-window counters"],
                        ),
                    ],
                ),
                GeneratedSectionItem(
                    title="6. DevOps, Distributed Architecture & Production Capstone",
                    description="Containerization, CI/CD pipelines, caching, background workers, and capstone deployment.",
                    order_index=6,
                    topics=[
                        GeneratedTopicItem(
                            title="Containerization with Docker & Multi-Stage Builds",
                            description="Dockerfiles, layers, multi-stage compilation for minimal production images, and Docker Compose.",
                            order_index=1,
                            difficulty="intermediate",
                            estimated_minutes=35,
                            prerequisites=["Modern Package Management & Build Toolchains"],
                            learning_objectives=["Author lightweight production container images", "Orchestrate local multi-service environments"],
                        ),
                        GeneratedTopicItem(
                            title="CI/CD Automation & Automated Testing Suites",
                            description="GitHub Actions workflows, unit testing, integration testing, lint checks, and automated deployment.",
                            order_index=2,
                            difficulty="intermediate",
                            estimated_minutes=35,
                            prerequisites=["Containerization with Docker & Multi-Stage Builds"],
                            learning_objectives=["Construct continuous integration pipelines", "Enforce automated quality gates on PRs"],
                        ),
                        GeneratedTopicItem(
                            title="Distributed Caching & Invalidation with Redis",
                            description="Cache-aside pattern, TTL management, cache stampede mitigation, and pub/sub messaging.",
                            order_index=3,
                            difficulty="advanced",
                            estimated_minutes=35,
                            prerequisites=["Database Indexing, B-Trees & Query Optimization"],
                            learning_objectives=["Implement Redis caching layers", "Eliminate cache invalidation race conditions"],
                        ),
                        GeneratedTopicItem(
                            title="Asynchronous Background Queues & WebSockets",
                            description="Decoupling slow tasks with message brokers, dead-letter queues, idempotent retry workers, and real-time sockets.",
                            order_index=4,
                            difficulty="advanced",
                            estimated_minutes=40,
                            prerequisites=["Distributed Caching & Invalidation with Redis"],
                            learning_objectives=["Implement durable asynchronous workers", "Establish real-time duplex WebSocket channels"],
                        ),
                        GeneratedTopicItem(
                            title="Full-Stack Production Capstone & Architecture Defense",
                            description="Integrating frontend, backend, PostgreSQL, and Redis into an observable, production-deployed SaaS.",
                            order_index=5,
                            difficulty="expert",
                            estimated_minutes=50,
                            prerequisites=[
                                "Global State Management & Cache Hydration",
                                "Layered Service Architecture & Middleware Pipelines",
                                "Relational Schema Normalization & Foreign Keys",
                                "CI/CD Automation & Automated Testing Suites",
                            ],
                            learning_objectives=["Deploy an observable full-stack production application", "Defend architectural decisions under scale constraints"],
                        ),
                    ],
                ),
            ]
        else:
            # Deep general engineering roadmap (6 modules, 25 topics)
            sections = [
                GeneratedSectionItem(
                    title=f"1. {clean_goal}: Architectural Foundations & Runtimes",
                    description="First principles, execution runtime, core memory models, and fundamental invariants.",
                    order_index=1,
                    topics=[
                        GeneratedTopicItem(
                            title="Execution Lifecycles & Runtime Models",
                            description=f"Internal architecture, execution phases, and boundary definitions for {clean_goal}.",
                            order_index=1,
                            difficulty="beginner" if not is_expert else "intermediate",
                            estimated_minutes=25,
                            prerequisites=[],
                            learning_objectives=["Deconstruct the runtime execution lifecycle", "Map subsystem boundaries"],
                        ),
                        GeneratedTopicItem(
                            title="Type Contracts, Schemas & Memory Representation",
                            description="Data types, structural schemas, pointer/reference semantics, and memory layout.",
                            order_index=2,
                            difficulty="intermediate",
                            estimated_minutes=30,
                            prerequisites=["Execution Lifecycles & Runtime Models"],
                            learning_objectives=["Define strongly typed structural contracts", "Analyze memory footprints"],
                        ),
                        GeneratedTopicItem(
                            title="Error Semantics & Exceptional State Machines",
                            description="Structured error representations, recoverable vs fatal invariants, and cleanup contracts.",
                            order_index=3,
                            difficulty="intermediate",
                            estimated_minutes=30,
                            prerequisites=["Type Contracts, Schemas & Memory Representation"],
                            learning_objectives=["Implement robust error handling pipelines", "Guarantee deterministic cleanup"],
                        ),
                        GeneratedTopicItem(
                            title="Development Tooling & Profiling Environments",
                            description="Toolchains, linting, debugging setups, and continuous feedback loops.",
                            order_index=4,
                            difficulty="intermediate",
                            estimated_minutes=25,
                            prerequisites=["Execution Lifecycles & Runtime Models"],
                            learning_objectives=["Configure automated verification toolchains", "Inspect runtime anomalies"],
                        ),
                    ],
                ),
                GeneratedSectionItem(
                    title=f"2. {clean_goal}: Core Patterns & Implementation",
                    description="Decoupled design, domain modeling, state management, and interface contracts.",
                    order_index=2,
                    topics=[
                        GeneratedTopicItem(
                            title="Domain Invariants & Business Logic Encapsulation",
                            description="Pure domain models, validation barriers, and state mutation boundaries.",
                            order_index=1,
                            difficulty="intermediate",
                            estimated_minutes=35,
                            prerequisites=["Type Contracts, Schemas & Memory Representation"],
                            learning_objectives=["Encapsulate domain rules within models", "Enforce business invariants"],
                        ),
                        GeneratedTopicItem(
                            title="Service Layer Decomposition & Dependency Inversion",
                            description="Decoupling infrastructure from business logic using interfaces and dependency injection.",
                            order_index=2,
                            difficulty="intermediate",
                            estimated_minutes=35,
                            prerequisites=["Domain Invariants & Business Logic Encapsulation"],
                            learning_objectives=["Decouple high-level modules from low-level details", "Write testable abstractions"],
                        ),
                        GeneratedTopicItem(
                            title="State Synchronization & Event Transitions",
                            description="Event-driven updates, reactive pipelines, and consistency models.",
                            order_index=3,
                            difficulty="intermediate",
                            estimated_minutes=30,
                            prerequisites=["Service Layer Decomposition & Dependency Inversion"],
                            learning_objectives=["Implement event-driven state transitions", "Maintain cross-component consistency"],
                        ),
                        GeneratedTopicItem(
                            title="Comprehensive Automated Testing Patterns",
                            description="Unit testing, test doubles, property-based tests, and coverage metrics.",
                            order_index=4,
                            difficulty="intermediate",
                            estimated_minutes=30,
                            prerequisites=["Service Layer Decomposition & Dependency Inversion"],
                            learning_objectives=["Author maintainable test suites", "Eliminate flaky test dependencies"],
                        ),
                    ],
                ),
                GeneratedSectionItem(
                    title=f"3. {clean_goal}: Data Persistence & Optimization",
                    description="Relational and key-value storage, indexing plans, and query performance.",
                    order_index=3,
                    topics=[
                        GeneratedTopicItem(
                            title="Storage Engine Internals & Data Modeling",
                            description="B-trees, LSM trees, schema normalization, and index selection.",
                            order_index=1,
                            difficulty="intermediate",
                            estimated_minutes=35,
                            prerequisites=["Domain Invariants & Business Logic Encapsulation"],
                            learning_objectives=["Design high-performance storage schemas", "Select optimal storage engines"],
                        ),
                        GeneratedTopicItem(
                            title="Query Optimization & Execution Plan Analysis",
                            description="Query analyzers, index scans, join algorithms, and bottleneck mitigation.",
                            order_index=2,
                            difficulty="advanced",
                            estimated_minutes=40,
                            prerequisites=["Storage Engine Internals & Data Modeling"],
                            learning_objectives=["Analyze execution plans", "Optimize complex relational queries"],
                        ),
                        GeneratedTopicItem(
                            title="Atomic Operations & Concurrency Control",
                            description="ACID transactions, optimistic vs pessimistic locking, and isolation trade-offs.",
                            order_index=3,
                            difficulty="advanced",
                            estimated_minutes=35,
                            prerequisites=["Query Optimization & Execution Plan Analysis"],
                            learning_objectives=["Execute atomic multi-resource transactions", "Prevent race hazards under concurrency"],
                        ),
                        GeneratedTopicItem(
                            title="Caching Topologies & Eviction Semantics",
                            description="In-memory caches, cache-aside patterns, TTLs, and stampede prevention.",
                            order_index=4,
                            difficulty="advanced",
                            estimated_minutes=35,
                            prerequisites=["Atomic Operations & Concurrency Control"],
                            learning_objectives=["Implement resilient cache topologies", "Manage cache invalidation reliably"],
                        ),
                    ],
                ),
                GeneratedSectionItem(
                    title=f"4. {clean_goal}: Security, Authentication & Protocols",
                    description="Cryptographic guarantees, identity verification, boundary sanitization, and defenses.",
                    order_index=4,
                    topics=[
                        GeneratedTopicItem(
                            title="Identity Verification & Cryptographic Standards",
                            description="Secure hashing, token lifecycles, and asymmetric key validation.",
                            order_index=1,
                            difficulty="intermediate",
                            estimated_minutes=30,
                            prerequisites=[],
                            learning_objectives=["Implement secure authentication primitives", "Manage key rotation securely"],
                        ),
                        GeneratedTopicItem(
                            title="Access Control & Boundary Enforcement",
                            description="Role-based and attribute-based permissions, gatekeepers, and policy evaluation.",
                            order_index=2,
                            difficulty="intermediate",
                            estimated_minutes=30,
                            prerequisites=["Identity Verification & Cryptographic Standards"],
                            learning_objectives=["Enforce least-privilege security policies", "Audit authorization boundaries"],
                        ),
                        GeneratedTopicItem(
                            title="Defensive Engineering & Attack Surface Reduction",
                            description="Input sanitization, injection mitigation, secure serialization, and timing-attack defenses.",
                            order_index=3,
                            difficulty="advanced",
                            estimated_minutes=35,
                            prerequisites=["Access Control & Boundary Enforcement"],
                            learning_objectives=["Harden applications against common attack vectors", "Eliminate injection surfaces"],
                        ),
                        GeneratedTopicItem(
                            title="Rate Limiting & Threat Throttling",
                            description="Sliding-window counters, token bucket algorithms, and brute-force mitigation.",
                            order_index=4,
                            difficulty="advanced",
                            estimated_minutes=30,
                            prerequisites=["Defensive Engineering & Attack Surface Reduction"],
                            learning_objectives=["Deploy distributed rate-limiting barriers", "Mitigate resource exhaustion attacks"],
                        ),
                    ],
                ),
                GeneratedSectionItem(
                    title=f"5. {clean_goal}: DevOps, CI/CD & Observability",
                    description="Containerization, automated release pipelines, telemetry, and structured debugging.",
                    order_index=5,
                    topics=[
                        GeneratedTopicItem(
                            title="Containerized Environments & Packaging",
                            description="Reproducible multi-stage container builds and environment parity.",
                            order_index=1,
                            difficulty="intermediate",
                            estimated_minutes=30,
                            prerequisites=[],
                            learning_objectives=["Package services into minimal secure containers", "Enforce environment parity"],
                        ),
                        GeneratedTopicItem(
                            title="Automated Release Pipelines & Quality Gates",
                            description="Continuous integration workflows, artifact versioning, and safe rollout stages.",
                            order_index=2,
                            difficulty="intermediate",
                            estimated_minutes=30,
                            prerequisites=["Containerized Environments & Packaging"],
                            learning_objectives=["Build automated CI/CD release pipelines", "Implement automated regression gates"],
                        ),
                        GeneratedTopicItem(
                            title="Structured Telemetry & Distributed Tracing",
                            description="Structured logging, Prometheus metrics, OpenTelemetry spans, and alerting thresholds.",
                            order_index=3,
                            difficulty="advanced",
                            estimated_minutes=35,
                            prerequisites=["Automated Release Pipelines & Quality Gates"],
                            learning_objectives=["Instrument distributed traces", "Detect production anomalies with telemetry"],
                        ),
                        GeneratedTopicItem(
                            title="Runtime Profiling & Bottleneck Diagnosis",
                            description="CPU and memory profiling, flame graphs, allocation tracking, and latency triage.",
                            order_index=4,
                            difficulty="advanced",
                            estimated_minutes=35,
                            prerequisites=["Structured Telemetry & Distributed Tracing"],
                            learning_objectives=["Profile production services under load", "Eliminate CPU and memory bottlenecks"],
                        ),
                    ],
                ),
                GeneratedSectionItem(
                    title=f"6. {clean_goal}: Distributed Scale & Capstone Architecture",
                    description="Horizontal scaling, consensus models, fault tolerance, and capstone synthesis.",
                    order_index=6,
                    topics=[
                        GeneratedTopicItem(
                            title="Asynchronous Messaging & Decoupled Workers",
                            description="Message queues, event streaming, consumer groups, and idempotency guarantees.",
                            order_index=1,
                            difficulty="advanced",
                            estimated_minutes=40,
                            prerequisites=["Storage Engine Internals & Data Modeling"],
                            learning_objectives=["Architect event-driven decoupled systems", "Ensure message processing idempotency"],
                        ),
                        GeneratedTopicItem(
                            title="Distributed Consistency & Horizontal Partitioning",
                            description="CAP theorem trade-offs, consistent hashing, replication topologies, and split-brain defenses.",
                            order_index=2,
                            difficulty="expert",
                            estimated_minutes=45,
                            prerequisites=["Asynchronous Messaging & Decoupled Workers"],
                            learning_objectives=["Select appropriate distributed consistency models", "Design horizontal sharding schemes"],
                        ),
                        GeneratedTopicItem(
                            title="Resilience Patterns (Circuit Breakers & Backpressure)",
                            description="Bulkheads, timeouts, circuit breakers, graceful degradation, and load shedding.",
                            order_index=3,
                            difficulty="expert",
                            estimated_minutes=35,
                            prerequisites=["Distributed Consistency & Horizontal Partitioning"],
                            learning_objectives=["Implement circuit breakers and backpressure", "Prevent cascading system failures"],
                        ),
                        GeneratedTopicItem(
                            title="End-to-End Production Capstone & Architecture Defense",
                            description=f"Designing and deploying a production-grade system fulfilling {clean_goal} under scale constraints.",
                            order_index=4,
                            difficulty="expert",
                            estimated_minutes=50,
                            prerequisites=[
                                "Execution Lifecycles & Runtime Models",
                                "Service Layer Decomposition & Dependency Inversion",
                                "Atomic Operations & Concurrency Control",
                                "Distributed Consistency & Horizontal Partitioning",
                            ],
                            learning_objectives=["Synthesize all architectural layers into a deployable product", "Defend system trade-offs in technical evaluations"],
                        ),
                    ],
                ),
            ]

        total_topics = sum(len(s.topics) for s in sections)
        return GeneratedHierarchicalPath(
            title=f"{clean_goal} Comprehensive Mastery",
            description=f"In-depth professional curriculum with {len(sections)} modular sections and {total_topics} topics designed to achieve verified {lvl} competence in {clean_goal}.",
            target_level=lvl,
            estimated_duration="10-14 weeks",
            sections=sections,
        )


learning_path_service = LearningPathService()

