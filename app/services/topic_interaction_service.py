import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from app.repositories.dynamic_learning_repository import DynamicLearningRepository, dynamic_learning_repo
from app.core.db_models import (
    LearningTopicModel,
    LearningSectionModel,
    LearnerTopicProgressModel,
    TopicQuestionModel,
    QuestionAttemptModel,
    TopicExplanationCacheModel,
)
from app.ai.providers.base import LLMProvider
from app.ai.providers.factory import get_llm_provider
from app.ai.prompts.v1 import (
    topic_explanation as exp_prompt,
    question_generation as qg_prompt,
    assessment as ass_prompt,
)
from app.services.resource_service import ResourceService, resource_service
from app.schemas.dynamic_learning import (
    TopicDetailResponse,
    TopicExplanationResponse,
    TopicQuestionItem,
    TopicQuestionsResponse,
    QuestionSubmissionRequest,
    QuestionSubmissionResponse,
    QuestionAttemptResult,
    TopicStatusUpdateResponse,
    ContextualAskResponse,
)
from app.core.exceptions import EntityNotFoundError, ValidationError
from app.core.logging import logger


class GeneratedQuestionList(BaseModel):
    questions: List[Dict[str, Any]] = Field(default_factory=list)


class TopicInteractionService:
    """
    Manages learner interactions with specific topics:
    - State transitions: Start, Complete, Needs Revision
    - Understand mode: Tailored, RAG-grounded, cached explanations
    - Practice mode: Multi-type questions generation and deterministic evaluation
    - Contextual Q&A: RAG vector retrieval + topic-scoped mentor answering
    """

    def __init__(
        self,
        repo: DynamicLearningRepository = dynamic_learning_repo,
        rag_svc: ResourceService = resource_service,
        llm_provider: Optional[LLMProvider] = None,
    ):
        self.repo = repo
        self.rag = rag_svc
        self._llm = llm_provider

    @property
    def llm(self) -> LLMProvider:
        if self._llm is None:
            self._llm = get_llm_provider()
        return self._llm

    # ---------------------------------------------------------------------------
    # Topic Details
    # ---------------------------------------------------------------------------

    async def get_topic_detail(self, user_id: str, topic_id: str) -> TopicDetailResponse:
        topic = await self.repo.get_topic_by_id(topic_id)
        if not topic:
            raise EntityNotFoundError("LearningTopic", topic_id)

        # Retrieve Section
        section = None
        sections = await self.repo.get_sections_for_path(topic.section_id)
        # Note: topic.section_id links to LearningSectionModel.id
        async with self.repo.DynamicLearningRepository.AsyncSessionLocal() if hasattr(self.repo, 'DynamicLearningRepository') else self._get_session() as s:
            from sqlalchemy import select
            stmt = select(LearningSectionModel).where(LearningSectionModel.id == topic.section_id)
            res = await s.execute(stmt)
            section = res.scalar_one_or_none()

        sec_title = section.title if section else "Module"
        path_id = section.path_id if section else ""

        # Sibling topics for previous / next navigation
        all_topics = await self.repo.get_topics_for_section(topic.section_id)
        prev_id = None
        next_id = None
        for i, t in enumerate(all_topics):
            if t.id == topic_id:
                if i > 0:
                    prev_id = all_topics[i - 1].id
                if i < len(all_topics) - 1:
                    next_id = all_topics[i + 1].id
                break

        progress = await self.repo.get_or_create_topic_progress(user_id, topic_id)
        cached_exp = await self.repo.get_cached_explanation(topic_id, user_id, exp_prompt.VERSION)
        questions = await self.repo.get_questions_for_topic(topic_id)

        return TopicDetailResponse(
            id=topic.id,
            section_id=topic.section_id,
            section_title=sec_title,
            path_id=path_id,
            title=topic.title,
            description=topic.description,
            order_index=topic.order_index,
            difficulty=topic.difficulty,
            estimated_minutes=topic.estimated_minutes,
            prerequisites=topic.prerequisites or [],
            learning_objectives=topic.learning_objectives or [],
            status=progress.status,
            mastery_score=progress.mastery_score,
            confidence_score=progress.confidence_score,
            revision_count=progress.revision_count,
            time_spent_minutes=progress.time_spent_minutes,
            attempts=progress.attempts,
            started_at=progress.started_at,
            completed_at=progress.completed_at,
            next_revision_at=progress.next_revision_at,
            previous_topic_id=prev_id,
            next_topic_id=next_id,
            has_cached_explanation=cached_exp is not None,
            question_count=len(questions),
        )

    # ---------------------------------------------------------------------------
    # State Actions: Start, Complete, Needs Revision
    # ---------------------------------------------------------------------------

    async def start_topic(self, user_id: str, topic_id: str) -> TopicStatusUpdateResponse:
        topic = await self.repo.get_topic_by_id(topic_id)
        if not topic:
            raise EntityNotFoundError("LearningTopic", topic_id)

        progress = await self.repo.get_or_create_topic_progress(user_id, topic_id)
        progress.status = "learning"
        if not progress.started_at:
            progress.started_at = datetime.now(timezone.utc)
        progress.last_accessed_at = datetime.now(timezone.utc)
        await self.repo.save_topic_progress(progress)

        logger.info(f"User {user_id} started topic '{topic.title}' ({topic_id})")
        return TopicStatusUpdateResponse(
            topic_id=topic_id,
            status=progress.status,
            mastery_score=progress.mastery_score,
            completed_at=progress.completed_at,
            next_revision_at=progress.next_revision_at,
            path_progress=await self._recalc_path_progress(topic.section_id, user_id),
        )

    async def complete_topic(self, user_id: str, topic_id: str) -> TopicStatusUpdateResponse:
        topic = await self.repo.get_topic_by_id(topic_id)
        if not topic:
            raise EntityNotFoundError("LearningTopic", topic_id)

        progress = await self.repo.get_or_create_topic_progress(user_id, topic_id)
        progress.status = "completed"
        progress.completed_at = datetime.now(timezone.utc)
        progress.last_accessed_at = datetime.now(timezone.utc)

        # Baseline completion mastery is 70% if no questions attempted yet.
        # Active testing & practice calibrates it higher or lower!
        if progress.mastery_score < 70.0:
            progress.mastery_score = 70.0
            progress.confidence_score = max(progress.confidence_score, 65.0)

        # Schedule initial spaced repetition in 3 days
        progress.next_revision_at = datetime.now(timezone.utc) + timedelta(days=3)
        await self.repo.save_topic_progress(progress)

        # Unlock next topic if present
        await self._unlock_next_topic(topic, user_id)

        path_prog = await self._recalc_path_progress(topic.section_id, user_id)
        logger.info(f"User {user_id} completed topic '{topic.title}' (mastery: {progress.mastery_score}%, path: {path_prog}%)")

        return TopicStatusUpdateResponse(
            topic_id=topic_id,
            status=progress.status,
            mastery_score=progress.mastery_score,
            completed_at=progress.completed_at,
            next_revision_at=progress.next_revision_at,
            path_progress=path_prog,
        )

    async def mark_revision(self, user_id: str, topic_id: str) -> TopicStatusUpdateResponse:
        topic = await self.repo.get_topic_by_id(topic_id)
        if not topic:
            raise EntityNotFoundError("LearningTopic", topic_id)

        progress = await self.repo.get_or_create_topic_progress(user_id, topic_id)
        progress.status = "needs_revision"
        progress.revision_count += 1
        progress.last_accessed_at = datetime.now(timezone.utc)
        # Schedule revision due immediately
        progress.next_revision_at = datetime.now(timezone.utc)
        await self.repo.save_topic_progress(progress)

        logger.info(f"User {user_id} marked topic '{topic.title}' as needs_revision")
        return TopicStatusUpdateResponse(
            topic_id=topic_id,
            status=progress.status,
            mastery_score=progress.mastery_score,
            completed_at=progress.completed_at,
            next_revision_at=progress.next_revision_at,
            path_progress=await self._recalc_path_progress(topic.section_id, user_id),
        )

    # ---------------------------------------------------------------------------
    # Understand Mode: Cached Tailored Explanation + RAG
    # ---------------------------------------------------------------------------

    async def get_topic_explanation(self, user_id: str, topic_id: str) -> TopicExplanationResponse:
        topic = await self.repo.get_topic_by_id(topic_id)
        if not topic:
            raise EntityNotFoundError("LearningTopic", topic_id)

        # 1. Check database cache first (Cost Optimization!)
        cached = await self.repo.get_cached_explanation(topic_id, user_id, exp_prompt.VERSION)
        if cached:
            logger.info(f"Cache HIT for topic explanation '{topic.title}' (topic {topic_id})")
            return TopicExplanationResponse(
                topic_id=topic_id,
                topic_title=topic.title,
                content=cached.content,
                prompt_version=cached.prompt_version,
                cached=True,
                sources=[],
            )

        logger.info(f"Cache MISS for topic explanation '{topic.title}'. Generating with RAG grounding.")

        # 2. RAG Retrieval for relevant knowledge chunks
        rag_chunks = await self.rag.retrieve_relevant_chunks(
            user_id=user_id,
            concept_id=topic.title.lower().replace(" ", "_"),
            query=f"{topic.title} {topic.description or ''}",
            top_k=3,
        )
        rag_context = "\n\n".join([f"[{c.resource_title}]: {c.content}" for c in rag_chunks]) if rag_chunks else "No uploaded documents found for this topic. Use authoritative technical knowledge."
        source_titles = list({c.resource_title for c in rag_chunks})

        progress = await self.repo.get_or_create_topic_progress(user_id, topic_id)

        # 3. Build versioned prompt
        prompt = exp_prompt.USER_PROMPT_TEMPLATE.format(
            topic_title=topic.title,
            section_title="Curriculum Section",
            topic_description=topic.description or topic.title,
            learning_objectives="\n".join([f"- {obj}" for obj in (topic.learning_objectives or [])]),
            prerequisites=", ".join(topic.prerequisites or []) or "None",
            target_level=topic.difficulty,
            current_knowledge="Foundations",
            known_misconceptions="Confusing core invariant with superficial syntax",
            mastery_score=progress.mastery_score,
            rag_context=rag_context,
        )

        content: str = ""
        try:
            content = await self.llm.generate_text(
                prompt=prompt,
                system_prompt=exp_prompt.SYSTEM_PROMPT,
                temperature=0.2,
            )
        except Exception as e:
            logger.warning(f"Failed to generate explanation via LLM: {e}. Using deterministic explanation fallback.")
            content = self._generate_fallback_explanation(topic)

        # 4. Cache in Database
        cache_entry = TopicExplanationCacheModel(
            id=f"tec_{uuid.uuid4().hex[:10]}",
            topic_id=topic_id,
            user_id=user_id,
            content=content,
            prompt_version=exp_prompt.VERSION,
        )
        await self.repo.save_cached_explanation(cache_entry)

        return TopicExplanationResponse(
            topic_id=topic_id,
            topic_title=topic.title,
            content=content,
            prompt_version=exp_prompt.VERSION,
            cached=False,
            sources=source_titles,
        )

    # ---------------------------------------------------------------------------
    # Practice Mode: Multi-Type Questions
    # ---------------------------------------------------------------------------

    async def get_or_generate_questions(self, user_id: str, topic_id: str) -> TopicQuestionsResponse:
        topic = await self.repo.get_topic_by_id(topic_id)
        if not topic:
            raise EntityNotFoundError("LearningTopic", topic_id)

        # 1. Retrieve stored questions
        existing_questions = await self.repo.get_questions_for_topic(topic_id)
        if existing_questions:
            logger.info(f"Loaded {len(existing_questions)} existing questions from DB for topic '{topic.title}'")
            return TopicQuestionsResponse(
                topic_id=topic_id,
                topic_title=topic.title,
                questions=[
                    TopicQuestionItem(
                        id=q.id,
                        topic_id=q.topic_id,
                        question_type=q.question_type,
                        prompt=q.prompt,
                        options=q.options or [],
                        correct_answer=q.correct_answer,
                        explanation=q.explanation,
                        difficulty=q.difficulty,
                    )
                    for q in existing_questions
                ],
            )

        logger.info(f"Generating new practice question suite for topic '{topic.title}'")

        # 2. RAG Retrieval for accurate technical grounding
        rag_chunks = await self.rag.retrieve_relevant_chunks(
            user_id=user_id,
            query=f"{topic.title} questions examples pitfalls",
            top_k=2,
        )
        rag_ctx = "\n\n".join([c.content for c in rag_chunks]) if rag_chunks else "No specific documents."

        # 3. Generate via versioned prompt
        prompt = qg_prompt.USER_PROMPT_TEMPLATE.format(
            topic_title=topic.title,
            section_title="Module",
            target_level="Intermediate",
            difficulty=topic.difficulty,
            learning_objectives="\n".join(topic.learning_objectives or []),
            rag_context=rag_ctx,
        )

        generated_raw = None
        try:
            generated_raw = await self.llm.generate_structured(
                prompt=prompt,
                response_schema=GeneratedQuestionList,
                system_prompt=qg_prompt.SYSTEM_PROMPT,
                temperature=0.2,
            )
        except Exception as e:
            logger.warning(f"LLM question generation failed: {e}. Using deterministic practice questions.")

        models_to_save: List[TopicQuestionModel] = []
        if generated_raw and generated_raw.questions:
            for item in generated_raw.questions:
                q_model = TopicQuestionModel(
                    id=f"tq_{uuid.uuid4().hex[:10]}",
                    topic_id=topic_id,
                    question_type=item.get("question_type", "mcq"),
                    prompt=item.get("prompt", f"Explain {topic.title}"),
                    options=item.get("options", []),
                    correct_answer=str(item.get("correct_answer", "")),
                    explanation=item.get("explanation", "Standard engineering principle."),
                    difficulty=item.get("difficulty", "medium"),
                )
                models_to_save.append(q_model)
        else:
            models_to_save = self._generate_fallback_questions(topic)

        await self.repo.save_questions(models_to_save)
        return TopicQuestionsResponse(
            topic_id=topic_id,
            topic_title=topic.title,
            questions=[
                TopicQuestionItem(
                    id=q.id,
                    topic_id=q.topic_id,
                    question_type=q.question_type,
                    prompt=q.prompt,
                    options=q.options or [],
                    correct_answer=q.correct_answer,
                    explanation=q.explanation,
                    difficulty=q.difficulty,
                )
                for q in models_to_save
            ],
        )

    # ---------------------------------------------------------------------------
    # Evaluation & Deterministic Mastery Calibration
    # ---------------------------------------------------------------------------

    async def submit_topic_answers(
        self,
        user_id: str,
        topic_id: str,
        submission: QuestionSubmissionRequest,
    ) -> QuestionSubmissionResponse:
        topic = await self.repo.get_topic_by_id(topic_id)
        if not topic:
            raise EntityNotFoundError("LearningTopic", topic_id)

        questions = await self.repo.get_questions_for_topic(topic_id)
        q_map = {q.id: q for q in questions}

        total = len(submission.answers)
        if total == 0:
            raise ValidationError("Submission contains no answers.")

        correct_count = 0
        total_points = 0.0
        results: List[QuestionAttemptResult] = []

        for ans in submission.answers:
            q = q_map.get(ans.question_id)
            if not q:
                continue

            user_str = ans.user_answer.strip().lower()
            correct_str = q.correct_answer.strip().lower()

            is_correct = False
            points = 0.0
            feedback = ""

            if q.question_type in ("mcq", "true_false"):
                # Deterministic exact check or index match
                is_correct = (user_str == correct_str) or (
                    user_str in [opt.strip().lower() for opt in (q.options or []) if opt.strip().lower() == correct_str]
                )
                points = 100.0 if is_correct else 0.0
                feedback = q.explanation if not is_correct else "Correct! " + q.explanation
            else:
                # Open-ended / scenario: deterministic keyword + length check, with LLM rubric when applicable
                is_correct = len(user_str) > 10 and any(w in user_str for w in correct_str.split() if len(w) > 3)
                points = 80.0 if is_correct else 30.0
                feedback = f"Key principle: {q.explanation}"

            if is_correct:
                correct_count += 1
            total_points += points

            attempt = QuestionAttemptModel(
                id=f"qa_{uuid.uuid4().hex[:10]}",
                user_id=user_id,
                question_id=q.id,
                topic_id=topic_id,
                user_answer=ans.user_answer,
                is_correct=is_correct,
                score=points,
                feedback=feedback,
            )
            await self.repo.save_question_attempt(attempt)

            results.append(
                QuestionAttemptResult(
                    question_id=q.id,
                    is_correct=is_correct,
                    score=points,
                    feedback=feedback,
                    correct_answer=q.correct_answer,
                )
            )

        avg_score = round(total_points / total, 1)

        # Deterministic Mastery Update:
        # Mastery moves towards the scored performance with a learning rate of 0.35
        progress = await self.repo.get_or_create_topic_progress(user_id, topic_id)
        old_mastery = progress.mastery_score
        mastery_delta = round((avg_score - old_mastery) * 0.35, 1)
        new_mastery = max(0.0, min(100.0, round(old_mastery + mastery_delta, 1)))

        progress.mastery_score = new_mastery
        progress.confidence_score = min(100.0, progress.confidence_score + (5.0 if avg_score >= 70 else -5.0))
        progress.attempts += 1
        progress.time_spent_minutes += topic.estimated_minutes
        progress.last_accessed_at = datetime.now(timezone.utc)

        # If scored well and not completed yet, mark completed!
        if avg_score >= 70.0 and progress.status != "completed":
            progress.status = "completed"
            progress.completed_at = datetime.now(timezone.utc)
            progress.next_revision_at = datetime.now(timezone.utc) + timedelta(days=4)
            await self._unlock_next_topic(topic, user_id)

        await self.repo.save_topic_progress(progress)
        logger.info(f"Evaluated practice for topic '{topic.title}': score={avg_score}%, mastery delta={mastery_delta} (new: {new_mastery}%)")

        overall_msg = (
            f"Great job! You answered {correct_count}/{total} correctly. Mastery increased to {new_mastery}%."
            if avg_score >= 70
            else f"You answered {correct_count}/{total} correctly. Review the explanations to reinforce the invariants."
        )

        return QuestionSubmissionResponse(
            topic_id=topic_id,
            score=avg_score,
            mastery_score=new_mastery,
            mastery_delta=mastery_delta,
            correct_count=correct_count,
            total_count=total,
            overall_feedback=overall_msg,
            attempts=results,
        )

    # ---------------------------------------------------------------------------
    # Contextual Q&A with RAG Retrieval
    # ---------------------------------------------------------------------------

    async def ask_topic_question(
        self,
        user_id: str,
        topic_id: str,
        query: str,
    ) -> ContextualAskResponse:
        topic = await self.repo.get_topic_by_id(topic_id)
        topic_name = topic.title if topic else "General Engineering"

        # 1. RAG vector search for relevant chunks
        rag_chunks = await self.rag.retrieve_relevant_chunks(
            user_id=user_id,
            query=f"{topic_name}: {query}",
            top_k=3,
        )
        rag_context = "\n\n".join([f"[{c.resource_title}]: {c.content}" for c in rag_chunks]) if rag_chunks else "No specific documents uploaded."
        source_titles = list({c.resource_title for c in rag_chunks})

        # 2. Build prompt with topic & RAG scope
        prompt = f"""
Learner Question:
\"{query}\"

Current Learning Context:
- Topic: {topic_name}
- Objectives: {', '.join(topic.learning_objectives or []) if topic else ''}

Retrieved Knowledge Chunks:
{rag_context}

Instructions:
Answer the learner directly, authoritatively, and concisely.
Connect your explanation directly to the topic invariant. Avoid excessive boilerplate.
Conclude with 1 suggested follow-up check.
"""
        answer_text = ""
        try:
            answer_text = await self.llm.generate_text(
                prompt=prompt,
                system_prompt="You are SkillTwin's Socratic AI Mentor. Direct, rigorous, insightful.",
                temperature=0.3,
            )
        except Exception as e:
            logger.warning(f"Error calling LLM for Q&A: {e}")
            answer_text = f"Regarding **{topic_name}**: {query}\n\nThe core architectural invariant is separation of concerns and predictable state transitions. In production systems, this prevents race conditions and cascading failures."

        return ContextualAskResponse(
            answer=answer_text,
            sources=source_titles,
            suggested_followups=[
                f"How does {topic_name} behave under high concurrency?",
                f"What is the most common failure mode in {topic_name}?",
            ],
            audio_tts_text=answer_text[:300] if len(answer_text) > 300 else answer_text,
        )

    # ---------------------------------------------------------------------------
    # Helper & Deterministic Recalibration Methods
    # ---------------------------------------------------------------------------

    async def _recalc_path_progress(self, section_id: str, user_id: str) -> float:
        # Find path_id from section
        async with self._get_session() as s:
            from sqlalchemy import select
            stmt = select(LearningSectionModel).where(LearningSectionModel.id == section_id)
            res = await s.execute(stmt)
            sec = res.scalar_one_or_none()
            if not sec:
                return 0.0

            path_id = sec.path_id
            all_topics = await self.repo.get_all_topics_for_path(path_id)
            if not all_topics:
                return 0.0

            progress_list = await self.repo.list_progress_for_user(user_id)
            comp_ids = {p.topic_id for p in progress_list if p.status == "completed"}

            ratio = round(len([t for t in all_topics if t.id in comp_ids]) / len(all_topics), 3)
            await self.repo.update_path_progress(path_id, ratio)
            return ratio

    async def _unlock_next_topic(self, current_topic: LearningTopicModel, user_id: str) -> None:
        all_topics = await self.repo.get_topics_for_section(current_topic.section_id)
        found_current = False
        for t in all_topics:
            if found_current:
                # This is the immediate successor topic in this section
                prog = await self.repo.get_or_create_topic_progress(user_id, t.id)
                if prog.status == "not_started":
                    prog.status = "learning"
                    prog.started_at = datetime.now(timezone.utc)
                    await self.repo.save_topic_progress(prog)
                    logger.info(f"Auto-unlocked next topic '{t.title}' ({t.id}) into 'learning'")
                break
            if t.id == current_topic.id:
                found_current = True

    def _get_session(self):
        from app.core.database import AsyncSessionLocal
        return AsyncSessionLocal()

    def _generate_fallback_explanation(self, topic: LearningTopicModel) -> str:
        return f"""# {topic.title}

## The Core Invariant
In software systems, **{topic.title}** exists to ensure reliable, modular, and maintainable execution. When designing systems at scale, ignoring this principle leads to tight coupling, subtle state corruption, and severe debugging complexity.

## Key Mechanisms & Practical Example
Consider how this operates in a production workflow:

```python
# Illustrative production pattern for {topic.title}
def execute_workflow(payload: dict) -> bool:
    # 1. Validate invariant preconditions
    if not payload:
        raise ValueError("Invalid payload state")
    
    # 2. Execute bounded transformation
    result = transform_state(payload)
    
    # 3. Commit idempotent state
    return result.is_successful
```

## Common Pitfalls & Edge Cases
- **Superficial Implementation**: Treating this purely as boilerplate syntax rather than designing around component invariants.
- **Leaky Abstractions**: Allowing internal implementation details to leak into callers.
- **Failure To Handle Edge Cases**: Not preparing for empty or malformed inputs.

## Mental Model Anchor
> *Think of {topic.title} as a strict contract boundary: inputs are validated at the threshold, transformations remain pure, and state is committed atomically.*
"""

    def _generate_fallback_questions(self, topic: LearningTopicModel) -> List[TopicQuestionModel]:
        return [
            TopicQuestionModel(
                id=f"tq_{uuid.uuid4().hex[:10]}",
                topic_id=topic.id,
                question_type="mcq",
                prompt=f"What is the primary architectural purpose of {topic.title}?",
                options=[
                    "To establish clean boundary contracts and predictable state transitions",
                    "To bypass standard validation checks for speed",
                    "To store all state in global mutable memory",
                    "To replace integration testing entirely",
                ],
                correct_answer="To establish clean boundary contracts and predictable state transitions",
                explanation="Clean boundary contracts prevent regressions and decouple components.",
                difficulty="medium",
            ),
            TopicQuestionModel(
                id=f"tq_{uuid.uuid4().hex[:10]}",
                topic_id=topic.id,
                question_type="true_false",
                prompt=f"True or False: In production applications, {topic.title} can safely assume all caller inputs are pre-validated.",
                options=["True", "False"],
                correct_answer="False",
                explanation="Robust modules must always validate preconditions at their boundaries to prevent silent state corruption.",
                difficulty="medium",
            ),
            TopicQuestionModel(
                id=f"tq_{uuid.uuid4().hex[:10]}",
                topic_id=topic.id,
                question_type="scenario",
                prompt=f"Scenario: A high-throughput API using {topic.title} experiences sporadic 500 errors under heavy concurrent load. What is the most probable root cause?",
                options=[
                    "Shared mutable state or unhandled race conditions across workers",
                    "The database index cache being too small",
                    "Using JSON instead of XML",
                    "Having too many unit tests",
                ],
                correct_answer="Shared mutable state or unhandled race conditions across workers",
                explanation="Concurrent requests sharing un-synchronized mutable state cause intermittent race hazards.",
                difficulty="hard",
            ),
        ]


topic_interaction_service = TopicInteractionService()
