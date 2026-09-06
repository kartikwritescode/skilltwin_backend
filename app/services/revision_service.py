import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from app.repositories.revision_repository import RevisionRepository, revision_repository
from app.repositories.concept_repository import ConceptRepository, concept_repository
from app.repositories.learner_repository import LearnerRepository, learner_repository
from app.repositories.goal_repository import GoalRepository, goal_repository
from app.services.retention_engine import RetentionEngine, retention_engine
from app.services.learner_service import LearnerService, learner_service
from app.domain.revision.models import (
    ReviewItem,
    RetrievalResult,
    RetrievalAccuracy,
    RetrievalConfidence,
)
from app.domain.sessions.models import EvidenceType
from app.schemas.revision import (
    RevisionNextResponse,
    ReviewItemResponse,
    ReviewCompleteRequest,
    ReviewSubmissionRequest,
    MentorNotification,
    MentorNotificationsResponse,
)
from app.core.exceptions import EntityNotFoundError
from app.core.logging import logger


class RevisionService:
    def __init__(
        self,
        revision_repo: RevisionRepository = revision_repository,
        concept_repo: ConceptRepository = concept_repository,
        learner_repo: LearnerRepository = learner_repository,
        goal_repo: GoalRepository = goal_repository,
        retention_eng: RetentionEngine = retention_engine,
        learner_svc: LearnerService = learner_service,
    ):
        self.revision_repo = revision_repo
        self.concept_repo = concept_repo
        self.learner_repo = learner_repo
        self.goal_repo = goal_repo
        self.retention_eng = retention_eng
        self.learner_svc = learner_svc

    async def get_next_retrieval(self, user_id: str) -> RevisionNextResponse:
        """
        Calculates live retention scores and multi-factor priorities for all user items,
        returning a small, focused, priority-ranked queue of due retrieval cards.
        """
        all_items = await self.revision_repo.list_all()
        user_items = [i for i in all_items if i.user_id == user_id]

        if not user_items:
            return RevisionNextResponse(
                header="5 minutes for your future self.",
                total_due_count=0,
                primary_review_item=None,
                upcoming_items=[],
                mentor_guidance="No revision items currently scheduled. Complete learning sessions to build your queue."
            )

        now = datetime.now(timezone.utc)
        active_goal = await self.goal_repo.get_active_goal_for_user(user_id)

        # 1. Update dynamic retention scores and multi-factor priorities
        for item in user_items:
            # Retention score decay
            item.retention_score = self.retention_eng.calculate_retention_score(
                last_reviewed=item.last_reviewed,
                interval_days=item.interval,
                successful_retrievals=item.successful_retrievals,
                failed_retrievals=item.failed_retrievals,
                now=now,
            )
            item.retention_risk = self.retention_eng.determine_retention_risk(item.retention_score)

            is_goal_relevant = True
            if active_goal and hasattr(active_goal, "target_domain"):
                is_goal_relevant = True  # Concepts connected to active journey

            concept = await self.concept_repo.get_by_id(item.concept_id)
            concept_importance = 1.2 if concept and concept.difficulty_level == "advanced" else 1.0

            priority, is_high, rationale = self.retention_eng.calculate_priority(
                last_reviewed=item.last_reviewed,
                next_review=item.next_review,
                retention_score=item.retention_score,
                retention_risk=item.retention_risk,
                is_goal_relevant=is_goal_relevant,
                concept_importance=concept_importance,
                failed_retrievals=item.failed_retrievals,
                now=now,
            )
            item.priority_score = priority
            item.is_high_priority = is_high
            if rationale:
                item.why_today = f"Why today: {rationale.capitalize()}."

            await self.revision_repo.save(item)

        # 2. Filter due items (next_review <= now)
        due_items = [i for i in user_items if i.next_review <= now]
        if not due_items:
            due_items = user_items  # Fallback to upcoming items

        # 3. Sort strictly by Priority Score descending (highest priority first)
        due_items.sort(key=lambda x: x.priority_score, reverse=True)

        primary_domain_item = due_items[0] if due_items else None
        primary_response = None
        if primary_domain_item:
            primary_response = self._to_response(primary_domain_item)

        # Non-overwhelming queue: small list (max 2 upcoming items)
        upcoming = [self._to_response(item) for item in due_items[1:3]]

        return RevisionNextResponse(
            header="5 minutes for your future self.",
            total_due_count=len(due_items),
            primary_review_item=primary_response,
            upcoming_items=upcoming,
            mentor_guidance="5 minutes of active retrieval prevents forgetting decay and locks in foundational invariants."
        )

    async def complete_review(
        self,
        user_id: str,
        review_id: str,
        request: ReviewCompleteRequest,
    ) -> ReviewItemResponse:
        """
        Completes a spaced retrieval practice session.
        Applies RetentionEngine:
        - Gradually reduces review frequency (expands interval) on successful retrieval.
        - Contracts interval on failure.
        - Recalibrates next_review, retention_score, and composite priority.
        - Synchronizes evidence proof with LearnerService.
        """
        item = await self.revision_repo.get_by_id(review_id)
        if not item:
            raise EntityNotFoundError("ReviewItem", review_id)

        now = datetime.now(timezone.utc)
        item.last_reviewed = now

        if request.is_successful:
            item.successful_retrievals += 1
            # Gradually reduce review frequency
            new_interval = self.retention_eng.calculate_next_interval(
                current_interval=item.interval,
                is_successful=True,
                consecutive_successes=item.successful_retrievals,
            )
            item.interval = new_interval
            score = 92.0
            next_review_text = f"Next review in {new_interval} {'day' if new_interval == 1 else 'days'}."
        else:
            item.failed_retrievals += 1
            # Contract interval for urgent reinforcement
            new_interval = self.retention_eng.calculate_next_interval(
                current_interval=item.interval,
                is_successful=False,
            )
            item.interval = new_interval
            score = 35.0
            next_review_text = "Next review in 1 day."

        item.next_review = now + timedelta(days=item.interval)
        item.next_review_text = next_review_text

        # Recalculate retention & priority with updated metrics
        item.retention_score = self.retention_eng.calculate_retention_score(
            last_reviewed=item.last_reviewed,
            interval_days=item.interval,
            successful_retrievals=item.successful_retrievals,
            failed_retrievals=item.failed_retrievals,
            now=now,
            last_was_failure=not request.is_successful,
        )
        item.retention_risk = self.retention_eng.determine_retention_risk(item.retention_score)

        priority, is_high, _ = self.retention_eng.calculate_priority(
            last_reviewed=item.last_reviewed,
            next_review=item.next_review,
            retention_score=item.retention_score,
            retention_risk=item.retention_risk,
            is_goal_relevant=True,
            failed_retrievals=item.failed_retrievals,
            now=now,
        )
        item.priority_score = priority
        item.is_high_priority = is_high

        await self.revision_repo.save(item)

        # Synchronize Learner Twin Model (evidence proof + memory reset)
        try:
            await self.learner_svc.record_evidence(
                user_id=user_id,
                concept_id=item.concept_id,
                evidence_type=EvidenceType.DELAYED_RETRIEVAL,
                score=score,
                feedback=f"Spaced retrieval completed (success={request.is_successful}). {next_review_text}",
                self_confidence=request.confidence or (85.0 if request.is_successful else 50.0),
            )
        except Exception as e:
            logger.warning(f"Could not record evidence during revision complete: {e}")

        logger.info(
            f"ReviewItem {item.id} completed for user {user_id}. Success={request.is_successful}. {next_review_text}"
        )

        return self._to_response(item)

    async def submit_retrieval(
        self, user_id: str, submission: ReviewSubmissionRequest
    ) -> ReviewItemResponse:
        """Backwards-compatible handler for existing submit endpoint."""
        is_successful = True
        if submission.accuracy is not None:
            is_successful = submission.accuracy in (RetrievalAccuracy.CORRECT, RetrievalAccuracy.PARTIALLY_CORRECT)
        elif submission.result is not None:
            is_successful = submission.result in (RetrievalResult.GOOD, RetrievalResult.EASY)

        req = ReviewCompleteRequest(
            is_successful=is_successful,
            confidence=85.0 if submission.confidence == RetrievalConfidence.CONFIDENT else 60.0,
            time_spent_seconds=submission.time_spent_seconds,
            notes=submission.notes,
        )
        return await self.complete_review(user_id=user_id, review_id=submission.review_item_id, request=req)

    async def get_mentor_notifications(self, user_id: str) -> MentorNotificationsResponse:
        all_items = await self.revision_repo.list_all()
        user_items = [i for i in all_items if i.user_id == user_id]

        notifications: List[MentorNotification] = []
        now = datetime.now(timezone.utc)

        # Prioritize high-risk or high-priority review items
        high_pri = [i for i in user_items if i.is_high_priority or i.retention_risk == "high"]
        target_item = high_pri[0] if high_pri else (user_items[0] if user_items else None)

        if target_item:
            notifications.append(
                MentorNotification(
                    id=f"notif_{uuid.uuid4().hex[:8]}",
                    title="5 minutes for your future self.",
                    message=f"Memory retention for '{target_item.concept_name}' is decaying. A quick retrieval session now stops forgetting.",
                    concept_id=target_item.concept_id,
                    notification_type="REVISION_DUE",
                    created_at=now,
                    is_read=False,
                    action_url=f"/revision?concept_id={target_item.concept_id}",
                )
            )

        return MentorNotificationsResponse(
            unread_count=len(notifications),
            notifications=notifications,
        )

    def _to_response(self, item: ReviewItem) -> ReviewItemResponse:
        return ReviewItemResponse(
            id=item.id,
            concept_id=item.concept_id,
            concept_name=item.concept_name,
            last_reviewed=item.last_reviewed,
            next_review=item.next_review,
            interval=item.interval,
            successful_retrievals=item.successful_retrievals,
            failed_retrievals=item.failed_retrievals,
            retention_score=item.retention_score,
            priority_score=item.priority_score,
            is_high_priority=item.is_high_priority,
            retention_risk=item.retention_risk,
            why_today=item.why_today,
            mentor_prompt=item.mentor_prompt or "Give me 5 minutes. I want to check whether your mental model is intact.",
            estimated_minutes=item.estimated_minutes or 4,
            next_review_text=item.next_review_text or f"Next review in {item.interval} {'day' if item.interval == 1 else 'days'}.",
            due_at=item.next_review,
            interval_days=item.interval,
            repetitions=item.repetitions,
            last_reviewed_at=item.last_reviewed,
            ease_factor=item.ease_factor,
        )


revision_service = RevisionService()
