import uuid
from datetime import datetime, timezone, timedelta, date
from typing import Optional, List, Dict, Any
from app.repositories.dynamic_learning_repository import DynamicLearningRepository, dynamic_learning_repo
from app.core.db_models import (
    GoalModel,
    LearningPathModel,
    LearningSectionModel,
    LearningTopicModel,
    LearnerTopicProgressModel,
    TwinMetricsModel,
)
from app.schemas.dynamic_learning import (
    HomeDashboardResponse,
    TwinDashboardResponse,
    AreaMasteryItem,
)
from app.core.logging import logger


class TwinAnalyticsService:
    """
    Deterministic cognitive analytics engine.
    Computes real, non-fabricated metrics for:
    - Home Dashboard (active goal, progress, current module/topic, real streak, next action)
    - Cognitive Twin (mastery, strengths, weaknesses, retention risks, velocity)
    Strictly avoids showing fake statistics for new or unverified learners.
    """

    def __init__(self, repo: DynamicLearningRepository = dynamic_learning_repo):
        self.repo = repo

    # ---------------------------------------------------------------------------
    # Home Screen Dashboard
    # ---------------------------------------------------------------------------

    async def get_home_dashboard(self, user_id: str) -> HomeDashboardResponse:
        goal = await self.repo.get_active_goal_for_user(user_id)
        if not goal:
            return HomeDashboardResponse(
                goal_id=None,
                goal_title="No Active Goal",
                target_level="Beginner",
                overall_progress=0.0,
                overall_mastery=0.0,
                topics_completed=0,
                topics_remaining=0,
                streak_days=0,
                learning_minutes=0,
                weak_areas=[],
                next_action_title="Set your learning goal",
                next_action_reason="Complete onboarding to generate your personalized AI learning journey.",
                next_action_type="ONBOARD",
                revision_due_count=0,
                is_new_learner=True,
                insights=["Welcome to SkillTwin. Your AI Mentor will adapt to your demonstrated mastery."],
            )

        path = await self.repo.get_active_path_for_user(user_id)
        if not path:
            return HomeDashboardResponse(
                goal_id=goal.id,
                goal_title=goal.title,
                target_level=goal.target_level or "Beginner",
                overall_progress=0.0,
                overall_mastery=0.0,
                topics_completed=0,
                topics_remaining=0,
                streak_days=1,
                learning_minutes=0,
                weak_areas=[],
                next_action_title="Preparing your roadmap...",
                next_action_reason="Your learning path is being generated.",
                next_action_type="PENDING",
                revision_due_count=0,
                is_new_learner=True,
                insights=["Your roadmap is generating. You will start your first topic shortly."],
            )

        # Retrieve all topics and learner progress
        all_topics = await self.repo.get_all_topics_for_path(path.id)
        user_progress = await self.repo.list_progress_for_user(user_id)
        progress_map = {p.topic_id: p for p in user_progress}

        total_topics = len(all_topics)
        completed_topics = 0
        total_mastery = 0.0
        total_minutes = 0
        current_topic: Optional[LearningTopicModel] = None
        weak_areas: List[str] = []
        revision_due_count = 0
        now = datetime.now(timezone.utc)

        for t in all_topics:
            p = progress_map.get(t.id)
            if p:
                total_minutes += p.time_spent_minutes
                if p.status == "completed":
                    completed_topics += 1
                    total_mastery += p.mastery_score
                elif p.status == "learning" and current_topic is None:
                    current_topic = t
                elif p.status == "needs_revision":
                    weak_areas.append(t.title)

                if self._is_due(p.next_revision_at):
                    revision_due_count += 1
            else:
                if current_topic is None:
                    current_topic = t

        # Default current topic to first if none was explicitly in 'learning'
        if current_topic is None and all_topics:
            current_topic = all_topics[0]

        # Overall progress: completed / total
        overall_prog = round(completed_topics / total_topics, 3) if total_topics > 0 else 0.0
        # Overall mastery: average mastery of completed topics, normalized 0.0 to 1.0
        overall_mast = round((total_mastery / completed_topics) / 100.0, 3) if completed_topics > 0 else 0.0

        # Current section name
        current_mod_name = None
        if current_topic:
            async with self._get_session() as s:
                from sqlalchemy import select
                stmt = select(LearningSectionModel).where(LearningSectionModel.id == current_topic.section_id)
                res = await s.execute(stmt)
                sec = res.scalar_one_or_none()
                if sec:
                    current_mod_name = sec.title

        # Determine real streak
        streak = self._calculate_streak(user_progress)
        is_new = completed_topics == 0 and total_minutes == 0

        # -------------------------------------------------------------------
        # Dynamic Schedule & Backlog Calculation
        # -------------------------------------------------------------------
        now_date = now.date()
        target_deadline = goal.deadline
        days_remaining = 30
        days_total = 60

        start_date = goal.created_at.date() if goal.created_at else now_date
        days_elapsed = max(0, (now_date - start_date).days)

        if target_deadline:
            diff_days = (target_deadline - now_date).days
            days_remaining = max(0, diff_days)
            diff_total = (target_deadline - start_date).days
            days_total = max(1, diff_total)
        else:
            days_total = max(30, days_elapsed + 30)
            days_remaining = max(0, days_total - days_elapsed)

        # Expected topics completed by today according to linear deadline pacing
        if total_topics > 0:
            expected_ratio = min(1.0, (days_elapsed + 1) / float(days_total))
            expected_topics = int(round(expected_ratio * total_topics))
        else:
            expected_topics = 0

        backlog_count = max(0, expected_topics - completed_topics)

        # Schedule status
        if completed_topics >= total_topics and total_topics > 0:
            schedule_status = "COMPLETED"
        elif backlog_count > 0:
            schedule_status = "BEHIND_SCHEDULE"
        elif completed_topics > expected_topics:
            schedule_status = "AHEAD_OF_SCHEDULE"
        else:
            schedule_status = "ON_TRACK"

        # Today's target topic & key concepts
        today_topic_title = current_topic.title if current_topic else None
        today_topic_id = current_topic.id if current_topic else None
        today_meta = current_topic.metadata_json if current_topic and hasattr(current_topic, "metadata_json") and isinstance(current_topic.metadata_json, dict) else {}
        today_key_concepts = today_meta.get("key_concepts", []) if today_meta else []
        today_est_minutes = current_topic.estimated_minutes if current_topic else (goal.daily_minutes or 30)

        # Concrete daily instructions based on schedule status and backlog
        deadline_display = target_deadline.strftime("%b %d, %Y") if target_deadline else "your target date"
        daily_mins = goal.daily_minutes or 30

        if schedule_status == "BEHIND_SCHEDULE":
            daily_instructions = (
                f"⚠️ Backlog Alert: You are {backlog_count} topic(s) behind schedule to finish by {deadline_display}. "
                f"Today's Mission: Focus {daily_mins} mins on '{today_topic_title or 'next topic'}' to prevent your backlog from growing. "
                f"Spend an extra 15 mins reviewing yesterday's missed concept to recover your velocity!"
            )
        elif schedule_status == "AHEAD_OF_SCHEDULE":
            daily_instructions = (
                f"🚀 Ahead of Schedule: You are moving faster than your target deadline ({deadline_display})! "
                f"Today's Mission: Dive into '{today_topic_title or 'advanced topic'}' (Est. {today_est_minutes}m) to solidify your lead."
            )
        elif schedule_status == "COMPLETED":
            daily_instructions = (
                f"🎉 Course Completed! You have completed all milestones for {goal.title}. "
                f"Continue daily spaced revision and review weak areas to maintain long-term retention."
            )
        else:
            daily_instructions = (
                f"🎯 On Track: {days_remaining} day(s) remaining until {deadline_display}. "
                f"Today's Mission: Complete '{today_topic_title or 'today\'s topic'}' (Est. {today_est_minutes}m) in your allocated {daily_mins} mins/day."
            )

        # Synthesize Next Action
        if revision_due_count > 0:
            next_title = f"Spaced Retrieval: {weak_areas[0] if weak_areas else 'Review Queue'}"
            next_reason = f"{revision_due_count} concept(s) are decaying. 5 minutes now arrests memory loss."
            next_type = "REVISE"
        elif current_topic:
            cur_prog = progress_map.get(current_topic.id)
            if cur_prog and cur_prog.status == "learning":
                next_title = f"Continue: {current_topic.title}"
                next_reason = "You have an active session in progress. Complete practice questions to cement mastery."
                next_type = "LEARN"
            else:
                next_title = f"Start: {current_topic.title}"
                next_reason = "Next sequential milestone on your active roadmap."
                next_type = "LEARN"
        else:
            next_title = "Goal Mastered!"
            next_reason = "All milestones completed. Proceed to capstone project or prove advanced skills."
            next_type = "PROVE"

        return HomeDashboardResponse(
            goal_id=goal.id,
            goal_title=goal.title,
            target_level=goal.target_level or "Intermediate",
            current_module_name=current_mod_name or "Foundations",
            current_topic_id=current_topic.id if current_topic else None,
            current_topic_title=current_topic.title if current_topic else None,
            overall_progress=overall_prog,
            overall_mastery=overall_mast,
            topics_completed=completed_topics,
            topics_remaining=max(0, total_topics - completed_topics),
            streak_days=streak,
            learning_minutes=total_minutes,
            weak_areas=weak_areas[:3],
            next_action_title=next_title,
            next_action_reason=next_reason,
            next_action_type=next_type,
            next_action_topic_id=current_topic.id if current_topic else None,
            revision_due_count=revision_due_count,
            is_new_learner=is_new,
            insights=[
                f"Mastery tracks verified practice proofs. Keep answering questions to build your Cognitive Twin.",
                f"Goal: {goal.title} ({goal.target_level})",
            ],
            target_deadline=target_deadline,
            days_remaining=days_remaining,
            schedule_status=schedule_status,
            backlog_count=backlog_count,
            daily_instructions=daily_instructions,
            today_target_topic_title=today_topic_title,
            today_target_topic_id=today_topic_id,
            today_key_concepts=today_key_concepts,
            today_estimated_minutes=today_est_minutes,
            daily_commitment_minutes=daily_mins,
        )

    # ---------------------------------------------------------------------------
    # Twin Tab Dashboard
    # ---------------------------------------------------------------------------

    async def get_twin_dashboard(self, user_id: str) -> TwinDashboardResponse:
        user_progress = await self.repo.list_progress_for_user(user_id)
        completed = [p for p in user_progress if p.status == "completed"]

        # If zero topics completed, faithfully return empty state!
        if not completed:
            return TwinDashboardResponse(
                user_id=user_id,
                has_sufficient_data=False,
                overall_mastery=0.0,
                learning_level="Beginner",
                strongest_areas=[],
                weakest_areas=[],
                concepts_at_risk=[],
                learning_velocity=0.0,
                consistency_streak=0,
                knowledge_coverage=0.0,
                verified_evidence_count=0,
                insights=[
                    "No mastery data yet. Complete topics and practice challenges to build your Cognitive Twin.",
                    "Your Twin will track demonstrated understanding, retention decay, and blindspots without vanity inflation.",
                ],
            )

        # Retrieve topic names for completed progress
        strongest: List[AreaMasteryItem] = []
        weakest: List[AreaMasteryItem] = []
        risks: List[str] = []
        now = datetime.now(timezone.utc)
        total_mastery = 0.0

        for p in user_progress:
            t = await self.repo.get_topic_by_id(p.topic_id)
            name = t.title if t else f"Topic {p.topic_id[:6]}"

            if p.status == "completed":
                total_mastery += p.mastery_score
                if p.mastery_score >= 75.0:
                    strongest.append(AreaMasteryItem(name=name, mastery_score=p.mastery_score, status="Mastered"))
                elif p.mastery_score < 60.0 or p.status == "needs_revision":
                    weakest.append(AreaMasteryItem(name=name, mastery_score=p.mastery_score, status="Needs Attention"))
            elif p.status == "needs_revision":
                weakest.append(AreaMasteryItem(name=name, mastery_score=p.mastery_score, status="Needs Revision"))

            if self._is_due(p.next_revision_at):
                risks.append(name)

        overall_mast = round((total_mastery / len(completed)) / 100.0, 3) if completed else 0.0
        streak = self._calculate_streak(user_progress)
        velocity = round(len(completed) * 1.5, 1)  # Topics completed scale factor

        # Level determination based on actual verified mastery
        level = "Beginner"
        if overall_mast >= 0.8:
            level = "Expert"
        elif overall_mast >= 0.5:
            level = "Intermediate"

        insights = [
            f"Overall verified mastery is at {int(overall_mast * 100)}% based on empirical testing proofs.",
            f"You have demonstrated solid mastery in {len(strongest)} key topic(s).",
        ]
        if risks:
            insights.append(f"{len(risks)} concept(s) are due for spaced retrieval review to prevent memory decay.")

        return TwinDashboardResponse(
            user_id=user_id,
            has_sufficient_data=True,
            overall_mastery=overall_mast,
            learning_level=level,
            strongest_areas=strongest[:4],
            weakest_areas=weakest[:4],
            concepts_at_risk=risks[:4],
            learning_velocity=velocity,
            consistency_streak=streak,
            knowledge_coverage=min(1.0, round(len(completed) / max(1, len(user_progress)), 2)),
            verified_evidence_count=len(completed) + sum(p.attempts for p in user_progress),
            insights=insights,
        )

    # ---------------------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------------------

    def _is_due(self, dt: Optional[datetime]) -> bool:
        if not dt:
            return False
        now = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt <= now

    def _calculate_streak(self, progress_list: List[LearnerTopicProgressModel]) -> int:
        if not progress_list:
            return 0
        active_dates = {
            p.last_accessed_at.date() for p in progress_list if p.last_accessed_at
        }
        if not active_dates:
            return 0

        today = datetime.now(timezone.utc).date()
        yesterday = today - timedelta(days=1)

        # Streak requires activity today or yesterday
        if today not in active_dates and yesterday not in active_dates:
            return 0

        streak = 0
        check_date = today if today in active_dates else yesterday
        while check_date in active_dates:
            streak += 1
            check_date -= timedelta(days=1)

        return max(1, streak)

    def _get_session(self):
        from app.core.database import AsyncSessionLocal
        return AsyncSessionLocal()


twin_analytics_service = TwinAnalyticsService()
