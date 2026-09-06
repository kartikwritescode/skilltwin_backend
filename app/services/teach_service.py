import uuid
from datetime import datetime, timezone
from typing import Optional, List
from app.repositories.concept_repository import ConceptRepository, concept_repository
from app.repositories.learner_repository import LearnerRepository, learner_repository
from app.repositories.goal_repository import GoalRepository, goal_repository
from app.repositories.journey_repository import JourneyRepository, journey_repository
from app.services.evaluation_service import EvaluationService, evaluation_service
from app.services.learner_service import LearnerService, learner_service
from app.services.journey_service import JourneyService, journey_service
from app.domain.sessions.models import EvidenceType
from app.domain.journeys.models import NodeState
from app.domain.learner.models import MisconceptionStatus
from app.schemas.teach import TeachEvaluateRequest, TeachEvaluationResponse
from app.core.exceptions import EntityNotFoundError
from app.core.logging import logger


class TeachService:
    """
    Orchestrates the Teach Mode pipeline:
    Learner Context -> LLM Evaluator -> EvaluationService -> LearnerService -> Evidence & Journey Update.

    Enforces mandatory architectural separation: The LLM evaluator does NOT modify
    the learner state directly. Validated outputs are processed by EvaluationService,
    and state transitions are applied deterministically by LearnerService and MasteryEngine.
    """

    def __init__(
        self,
        concept_repo: ConceptRepository = concept_repository,
        learner_repo: LearnerRepository = learner_repository,
        goal_repo: GoalRepository = goal_repository,
        journey_repo: JourneyRepository = journey_repository,
        evaluation_svc: EvaluationService = evaluation_service,
        learner_svc: LearnerService = learner_service,
        journey_svc: JourneyService = journey_service,
    ):
        self.concept_repo = concept_repo
        self.learner_repo = learner_repo
        self.goal_repo = goal_repo
        self.journey_repo = journey_repo
        self.evaluation_svc = evaluation_svc
        self.learner_svc = learner_svc
        self.journey_svc = journey_svc

    async def evaluate_teach_session(
        self,
        user_id: str,
        request: TeachEvaluateRequest,
    ) -> TeachEvaluationResponse:
        logger.info(f"Teach Mode evaluation initiated for user {user_id}, concept {request.concept_id}")

        # 1. Validate Target Concept
        concept = await self.concept_repo.get_by_id(request.concept_id)
        if not concept:
            concept = await self.concept_repo.get_by_name_or_id(request.concept_id)
            if not concept:
                raise EntityNotFoundError("Concept", request.concept_id)

        # 2. Gather Learner Cognitive Context
        learner_state = await self.learner_svc.get_or_create_concept_state(user_id, concept.id)
        active_miscs = await self.learner_repo.list_misconceptions_for_concept(user_id, concept.id, active_only=True)
        prior_misc_tags = list(set(learner_state.misconception_tags + [m.tag for m in active_miscs]))

        active_goal = await self.goal_repo.get_active_goal_for_user(user_id)
        goal_title = active_goal.title if active_goal else "Software Engineering Mastery"

        # 3. LLM Evaluator Execution (Generates validated structured output without database writes)
        eval_ai_output = await self.evaluation_svc.evaluate_teaching_explanation(
            concept_name=concept.name,
            concept_description=concept.description,
            prerequisites=concept.prerequisites,
            explanation=request.explanation_text,
            mastery_score=learner_state.mastery_score,
            prior_misconceptions=prior_misc_tags,
            goal_title=goal_title,
        )

        # 4. Mandatory Separation: EvaluationService -> LearnerService Pipeline
        # Calculate composite evidence score
        composite_score = round(
            0.35 * eval_ai_output.conceptual_accuracy
            + 0.25 * eval_ai_output.reasoning
            + 0.20 * eval_ai_output.completeness
            + 0.20 * eval_ai_output.transfer,
            1,
        )

        effective_confidence = (
            float(request.self_reported_confidence)
            if request.self_reported_confidence is not None
            else float(eval_ai_output.confidence)
        )

        feedback_text = (
            eval_ai_output.feedback_summary
            or f"Teach-back evaluated: Accuracy={eval_ai_output.conceptual_accuracy}%, Reasoning={eval_ai_output.reasoning}%"
        )

        # Record verifiable proof of understanding in Evidence repository and update Learner Twin
        evidence = await self.learner_svc.record_evidence(
            user_id=user_id,
            concept_id=concept.id,
            evidence_type=EvidenceType.TEACH_BACK,
            score=composite_score,
            feedback=feedback_text,
            session_id=request.session_id,
            reasoning_score=float(eval_ai_output.reasoning),
            transfer_score=float(eval_ai_output.transfer),
            misconceptions_detected=eval_ai_output.misconceptions,
            self_confidence=effective_confidence,
        )

        # Fetch newly recalibrated Learner Model state
        updated_state = await self.learner_svc.get_or_create_concept_state(user_id, concept.id)

        # 5. Misconception Resolution Mechanics
        # If accuracy is strong (>= 80%) and no misconceptions were detected in this teach-back,
        # resolve any historical misconceptions for this concept.
        if eval_ai_output.conceptual_accuracy >= 80 and not eval_ai_output.misconceptions:
            if updated_state.misconception_tags:
                logger.info(
                    f"Teach-back verified sound understanding. Resolving misconceptions: {updated_state.misconception_tags}"
                )
                updated_state.misconception_tags.clear()
                for m in active_miscs:
                    m.status = MisconceptionStatus.RESOLVED
                    m.resolved_at = datetime.now(timezone.utc)
                    await self.learner_repo.save_misconception(m)

                updated_state.risk_score = self.learner_svc.update_risk(
                    updated_state.mastery_score,
                    updated_state.retention_score,
                    len(updated_state.misconception_tags),
                )
                await self.learner_repo.save_concept_state(updated_state)

        # 6. Journey Graph Synchronization
        if active_goal:
            journey = await self.journey_repo.get_by_goal_id(active_goal.id)
            if journey and journey.nodes:
                for node in journey.nodes:
                    if node.concept_id == concept.id and node.state == NodeState.CURRENT:
                        if updated_state.mastery_score >= 70.0:
                            logger.info(
                                f"Learner mastered concept {concept.id} via Teach Mode. Cascading journey unlock."
                            )
                            await self.journey_svc.update_node_state(journey.id, node.id, NodeState.COMPLETED)
                        break

        now = datetime.now(timezone.utc)

        return TeachEvaluationResponse(
            concept_id=concept.id,
            conceptual_accuracy=eval_ai_output.conceptual_accuracy,
            completeness=eval_ai_output.completeness,
            reasoning=eval_ai_output.reasoning,
            confidence=eval_ai_output.confidence,
            transfer=eval_ai_output.transfer,
            misconceptions=eval_ai_output.misconceptions,
            missing_concepts=eval_ai_output.missing_concepts,
            recommendation=eval_ai_output.recommendation,
            evidence_id=evidence.id if evidence else None,
            updated_mastery_score=updated_state.mastery_score,
            updated_confidence_score=updated_state.confidence_score,
            updated_status=updated_state.status.value,
            feedback_summary=eval_ai_output.feedback_summary,
            key_strengths=eval_ai_output.key_strengths,
            growth_areas=eval_ai_output.growth_areas,
            evaluated_at=now,
        )


teach_service = TeachService()
