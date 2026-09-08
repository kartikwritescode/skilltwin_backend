import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from sqlalchemy import select, update, delete, and_, desc, cast, String, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import AsyncSessionLocal
from app.core.db_models import (
    GoalModel,
    LearningGoalModel,
    LearningPathModel,
    LearningSectionModel,
    LearningTopicModel,
    TopicDependencyModel,
    LearnerTopicProgressModel,
    TopicQuestionModel,
    QuestionAttemptModel,
    TopicExplanationCacheModel,
    TwinMetricsModel,
)
from app.core.logging import logger


class DynamicLearningRepository:
    """
    Data access layer for SkillTwin's hierarchical learning paths,
    topics, learner progress, practice questions, and cognitive twin metrics.
    """

    async def _ensure_profile_exists(self, session: AsyncSession, user_id: Any) -> None:
        """
        Ensures a corresponding row exists in the profiles table for the given user_id
        to satisfy foreign key constraints before saving goals or paths.
        """
        if not user_id:
            return
        try:
            async with session.begin_nested():
                await session.execute(
                    text("INSERT INTO profiles (id, display_name) VALUES (:id, 'Learner') ON CONFLICT (id) DO NOTHING"),
                    {"id": str(user_id)}
                )
        except Exception as e:
            logger.warning(f"Could not auto-ensure profile for user {user_id}: {e}")

    async def _ensure_learning_goal_exists(
        self,
        session: AsyncSession,
        goal_id: Any,
        user_id: Any,
        learning_goal: str,
        target_level: str = "Intermediate",
        custom_target: Optional[str] = None,
        daily_minutes: int = 30,
        status: str = "ACTIVE",
    ) -> None:
        """
        Ensures a corresponding row exists in learning_goals for goal_id
        to satisfy foreign key constraints (learning_paths_goal_id_fkey).
        """
        if not goal_id or not user_id:
            return
        try:
            async with session.begin_nested():
                await session.execute(
                    text("""
                        INSERT INTO learning_goals (id, user_id, learning_goal, target_level, custom_target, daily_minutes, status)
                        VALUES (:id, :user_id, :learning_goal, :target_level, :custom_target, :daily_minutes, :status)
                        ON CONFLICT (id) DO UPDATE SET
                            learning_goal = EXCLUDED.learning_goal,
                            target_level = EXCLUDED.target_level,
                            custom_target = EXCLUDED.custom_target,
                            daily_minutes = EXCLUDED.daily_minutes,
                            status = EXCLUDED.status,
                            updated_at = CURRENT_TIMESTAMP
                    """),
                    {
                        "id": str(goal_id),
                        "user_id": str(user_id),
                        "learning_goal": str(learning_goal or "Learning Goal"),
                        "target_level": str(target_level or "Intermediate"),
                        "custom_target": str(custom_target) if custom_target else None,
                        "daily_minutes": int(daily_minutes or 30),
                        "status": str(status or "ACTIVE"),
                    }
                )
        except Exception as e:
            logger.warning(f"Could not auto-ensure learning_goals record for {goal_id}: {e}")

    # ---------------------------------------------------------------------------
    # Learning Goals
    # ---------------------------------------------------------------------------

    async def save_goal(self, goal: GoalModel) -> GoalModel:
        async with AsyncSessionLocal() as session:
            await self._ensure_profile_exists(session, goal.user_id)
            await self._ensure_learning_goal_exists(
                session,
                goal_id=goal.id,
                user_id=goal.user_id,
                learning_goal=goal.title,
                target_level=goal.target_level,
                custom_target=goal.custom_target,
                daily_minutes=goal.daily_minutes,
                status=str(goal.status or "ACTIVE"),
            )
            session.add(goal)
            await session.commit()
            await session.refresh(goal)
            return goal

    async def get_goal_by_id(self, goal_id: str) -> Optional[GoalModel]:
        async with AsyncSessionLocal() as session:
            stmt = select(GoalModel).where(GoalModel.id == goal_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_active_goal_for_user(self, user_id: str) -> Optional[GoalModel]:
        async with AsyncSessionLocal() as session:
            stmt = (
                select(GoalModel)
                .where(and_(GoalModel.user_id == user_id, cast(GoalModel.status, String) == "ACTIVE"))
                .order_by(desc(GoalModel.created_at))
            )
            result = await session.execute(stmt)
            return result.scalars().first()

    # ---------------------------------------------------------------------------
    # Learning Paths & Hierarchy
    # ---------------------------------------------------------------------------

    async def save_path(self, path: LearningPathModel) -> LearningPathModel:
        async with AsyncSessionLocal() as session:
            await self._ensure_profile_exists(session, path.user_id)
            await self._ensure_learning_goal_exists(
                session,
                goal_id=path.goal_id,
                user_id=path.user_id,
                learning_goal=path.title,
                target_level=path.target_level,
            )
            session.add(path)
            await session.commit()
            await session.refresh(path)
            return path

    async def get_path_by_id(self, path_id: str) -> Optional[LearningPathModel]:
        async with AsyncSessionLocal() as session:
            stmt = select(LearningPathModel).where(LearningPathModel.id == path_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_path_by_goal_id(self, goal_id: str) -> Optional[LearningPathModel]:
        async with AsyncSessionLocal() as session:
            stmt = select(LearningPathModel).where(LearningPathModel.goal_id == goal_id).order_by(desc(LearningPathModel.created_at))
            result = await session.execute(stmt)
            return result.scalars().first()

    async def get_active_path_for_user(self, user_id: str) -> Optional[LearningPathModel]:
        async with AsyncSessionLocal() as session:
            stmt = (
                select(LearningPathModel)
                .where(and_(LearningPathModel.user_id == user_id, cast(LearningPathModel.status, String) == "ACTIVE"))
                .order_by(desc(LearningPathModel.created_at))
            )
            result = await session.execute(stmt)
            return result.scalars().first()

    async def update_path_progress(self, path_id: str, progress: float) -> None:
        async with AsyncSessionLocal() as session:
            stmt = (
                update(LearningPathModel)
                .where(LearningPathModel.id == path_id)
                .values(progress=progress, updated_at=datetime.now(timezone.utc))
            )
            await session.execute(stmt)
            await session.commit()

    async def save_sections_and_topics(
        self,
        sections: List[LearningSectionModel],
        topics: List[LearningTopicModel],
    ) -> None:
        async with AsyncSessionLocal() as session:
            for s in sections:
                session.add(s)
            for t in topics:
                session.add(t)
            await session.commit()

    async def get_sections_for_path(self, path_id: str) -> List[LearningSectionModel]:
        async with AsyncSessionLocal() as session:
            stmt = select(LearningSectionModel).where(LearningSectionModel.path_id == path_id).order_by(LearningSectionModel.order_index)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_topics_for_section(self, section_id: str) -> List[LearningTopicModel]:
        async with AsyncSessionLocal() as session:
            stmt = select(LearningTopicModel).where(LearningTopicModel.section_id == section_id).order_by(LearningTopicModel.order_index)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_all_topics_for_path(self, path_id: str) -> List[LearningTopicModel]:
        async with AsyncSessionLocal() as session:
            stmt = (
                select(LearningTopicModel)
                .join(LearningSectionModel, LearningTopicModel.section_id == LearningSectionModel.id)
                .where(LearningSectionModel.path_id == path_id)
                .order_by(LearningSectionModel.order_index, LearningTopicModel.order_index)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_topic_by_id(self, topic_id: str) -> Optional[LearningTopicModel]:
        async with AsyncSessionLocal() as session:
            stmt = select(LearningTopicModel).where(LearningTopicModel.id == topic_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    # ---------------------------------------------------------------------------
    # Learner Topic Progress
    # ---------------------------------------------------------------------------

    async def get_topic_progress(self, user_id: str, topic_id: str) -> Optional[LearnerTopicProgressModel]:
        async with AsyncSessionLocal() as session:
            stmt = select(LearnerTopicProgressModel).where(
                and_(LearnerTopicProgressModel.user_id == user_id, LearnerTopicProgressModel.topic_id == topic_id)
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_or_create_topic_progress(self, user_id: str, topic_id: str) -> LearnerTopicProgressModel:
        async with AsyncSessionLocal() as session:
            stmt = select(LearnerTopicProgressModel).where(
                and_(LearnerTopicProgressModel.user_id == user_id, LearnerTopicProgressModel.topic_id == topic_id)
            )
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing:
                return existing

            await self._ensure_profile_exists(session, user_id)
            progress = LearnerTopicProgressModel(
                id=str(uuid.uuid4()),
                user_id=user_id,
                topic_id=topic_id,
                status="not_started",
                mastery_score=0.0,
                confidence_score=0.0,
                revision_count=0,
                time_spent_minutes=0,
                attempts=0,
                last_accessed_at=datetime.now(timezone.utc),
            )
            session.add(progress)
            await session.commit()
            await session.refresh(progress)
            return progress

    async def save_topic_progress(self, progress: LearnerTopicProgressModel) -> LearnerTopicProgressModel:
        async with AsyncSessionLocal() as session:
            await self._ensure_profile_exists(session, progress.user_id)
            session.add(progress)
            await session.commit()
            await session.refresh(progress)
            return progress

    async def list_progress_for_user(self, user_id: str) -> List[LearnerTopicProgressModel]:
        async with AsyncSessionLocal() as session:
            stmt = select(LearnerTopicProgressModel).where(LearnerTopicProgressModel.user_id == user_id)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    # ---------------------------------------------------------------------------
    # Cached Explanations
    # ---------------------------------------------------------------------------

    async def get_cached_explanation(self, topic_id: str, user_id: str, prompt_version: str = "v1") -> Optional[TopicExplanationCacheModel]:
        async with AsyncSessionLocal() as session:
            stmt = select(TopicExplanationCacheModel).where(
                and_(
                    TopicExplanationCacheModel.topic_id == topic_id,
                    TopicExplanationCacheModel.user_id == user_id,
                    TopicExplanationCacheModel.prompt_version == prompt_version,
                )
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def save_cached_explanation(self, cache_entry: TopicExplanationCacheModel) -> TopicExplanationCacheModel:
        async with AsyncSessionLocal() as session:
            session.add(cache_entry)
            await session.commit()
            await session.refresh(cache_entry)
            return cache_entry

    # ---------------------------------------------------------------------------
    # Practice Questions & Attempts
    # ---------------------------------------------------------------------------

    async def get_questions_for_topic(self, topic_id: str) -> List[TopicQuestionModel]:
        async with AsyncSessionLocal() as session:
            stmt = select(TopicQuestionModel).where(TopicQuestionModel.topic_id == topic_id)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def save_questions(self, questions: List[TopicQuestionModel]) -> None:
        async with AsyncSessionLocal() as session:
            for q in questions:
                session.add(q)
            await session.commit()

    async def save_question_attempt(self, attempt: QuestionAttemptModel) -> QuestionAttemptModel:
        async with AsyncSessionLocal() as session:
            session.add(attempt)
            await session.commit()
            await session.refresh(attempt)
            return attempt

    # ---------------------------------------------------------------------------
    # Twin Metrics
    # ---------------------------------------------------------------------------

    async def get_twin_metrics(self, user_id: str) -> Optional[TwinMetricsModel]:
        async with AsyncSessionLocal() as session:
            stmt = select(TwinMetricsModel).where(TwinMetricsModel.user_id == user_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def save_twin_metrics(self, metrics: TwinMetricsModel) -> TwinMetricsModel:
        async with AsyncSessionLocal() as session:
            await self._ensure_profile_exists(session, metrics.user_id)
            session.add(metrics)
            await session.commit()
            await session.refresh(metrics)
            return metrics


dynamic_learning_repo = DynamicLearningRepository()
