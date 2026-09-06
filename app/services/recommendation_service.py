import uuid
from typing import Optional, List, Tuple
from app.domain.mentor.models import (
    ActionType,
    ActionRecommendation,
    RecommendationRecord,
)
from app.repositories.recommendation_repository import RecommendationRepository, recommendation_repository
from app.ai.orchestrator.context_builder import MentorContextBuilder, context_builder, MentorContext
from app.ai.orchestrator.mentor_orchestrator import MentorOrchestrator
from app.ai.providers.factory import get_llm_provider
from app.schemas.mentor import ActionRecommendationSchema, MentorTodayResponse
from app.core.logging import logger


class RecommendationService:
    """
    Core AI Mentor Decision Engine:
    Deterministic-First Architecture:
    1. Evaluates deterministic pedagogical rules over learner state.
    2. Enforces invariant transitions (prerequisite gaps -> REMEDIATE, memory decay -> REVISE,
       unverified confidence -> PROVE).
    3. Employs the LLM Orchestrator exclusively for language generation, persona calibration,
       and pedagogical reasoning.
    4. Validates structured outputs via Pydantic.
    5. Persists an immutable recommendation audit record.
    """

    def __init__(
        self,
        ctx_builder: MentorContextBuilder = context_builder,
        rec_repo: RecommendationRepository = recommendation_repository,
        orchestrator: Optional[MentorOrchestrator] = None,
    ):
        self.ctx_builder = ctx_builder
        self.rec_repo = rec_repo
        self.orchestrator = orchestrator or MentorOrchestrator(get_llm_provider())

    def evaluate_deterministic_rules(self, ctx: MentorContext) -> Tuple[ActionType, str, str]:
        """
        Pure deterministic rules engine. Returns (ActionType, target_concept_id, rule_name).
        """
        # Rule 0: No active goal defined
        if not ctx.goal_id:
            return ActionType.REFLECT, "goal_onboarding", "NO_ACTIVE_GOAL"

        # Rule 1: Prerequisite mastery < threshold (60.0%) or not satisfied -> REMEDIATE
        for prereq in ctx.prerequisites:
            if not prereq.is_satisfied or prereq.mastery < 60.0:
                logger.info(f"Rule Matched [REMEDIATE]: Prerequisite '{prereq.title}' mastery ({prereq.mastery}%) < 60%")
                return ActionType.REMEDIATE, prereq.concept_id, "PREREQUISITE_DEFICIT"

        # Rule 2: High retention risk or high priority revision -> REVISE
        high_risk_decay = next(
            (
                item for item in ctx.due_retention_items
                if item.get("is_high_priority")
                or item.get("retention_risk") == "high"
                or item.get("priority_score", 0) >= 60.0
            ),
            None
        )
        if high_risk_decay:
            logger.info(
                f"Rule Matched [REVISE]: Concept '{high_risk_decay['concept_name']}' has high revision priority / retention risk"
            )
            return ActionType.REVISE, high_risk_decay["concept_id"], "HIGH_RETENTION_RISK"

        # Rule 3: High mastery (>= 75.0) but weak evidence (< 2 proofs) -> PROVE
        if ctx.current_concept_mastery >= 75.0 and ctx.current_evidence_count < 2:
            logger.info(f"Rule Matched [PROVE]: Mastery is {ctx.current_concept_mastery}% with only {ctx.current_evidence_count} proofs")
            return ActionType.PROVE, ctx.current_concept_id or "concept_active", "UNVERIFIED_MASTERY"

        # Rule 4: Active concept in progress: practice vs learn
        if ctx.current_concept_mastery >= 40.0:
            return ActionType.PRACTICE, ctx.current_concept_id or "concept_active", "ACTIVE_PRACTICE"

        # Rule 5: Standard forward progress along roadmap -> LEARN
        return ActionType.LEARN, ctx.current_concept_id or "concept_active", "PROGRESS_MILESTONE"

    async def get_today_recommendation(self, user_id: str) -> MentorTodayResponse:
        logger.info(f"Computing today's mentor recommendation for learner: {user_id}")
        from app.services.mentor_decision_pipeline import mentor_decision_pipeline
        return await mentor_decision_pipeline.execute(user_id)


recommendation_service = RecommendationService()
