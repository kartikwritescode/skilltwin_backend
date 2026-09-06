import uuid
from datetime import datetime, timezone
from typing import Optional, List
from app.repositories.session_repository import SessionRepository, session_repository
from app.repositories.concept_repository import ConceptRepository, concept_repository
from app.repositories.journey_repository import JourneyRepository, journey_repository
from app.repositories.goal_repository import GoalRepository, goal_repository
from app.repositories.recommendation_repository import RecommendationRepository, recommendation_repository
from app.repositories.learner_repository import LearnerRepository, learner_repository
from app.domain.sessions.models import (
    LearningSession,
    EvidenceRecord,
    SessionType,
    SessionStatus,
    EvidenceType,
    SessionStep,
    SessionStepType,
)
from app.domain.journeys.models import NodeState
from app.schemas.sessions import (
    SessionCreateRequest,
    SessionCompleteRequest,
    SessionResponse,
    SessionStepSchema,
    EvidenceSchema,
    StepEvaluationSchema,
)
from app.schemas.mentor import ActionRecommendationSchema
from app.services.assessment_service import AssessmentService, assessment_service
from app.services.learner_service import LearnerService, learner_service
from app.services.journey_service import JourneyService, journey_service
from app.services.recommendation_service import RecommendationService, recommendation_service
from app.services.evidence_service import EvidenceService, evidence_service
from app.ai.generators.question_generator import QuestionGenerator, question_generator
from app.core.exceptions import EntityNotFoundError
from app.core.logging import logger


class SessionService:
    def __init__(
        self,
        session_repo: SessionRepository = session_repository,
        concept_repo: ConceptRepository = concept_repository,
        journey_repo: JourneyRepository = journey_repository,
        goal_repo: GoalRepository = goal_repository,
        rec_repo: RecommendationRepository = recommendation_repository,
        learner_repo: LearnerRepository = learner_repository,
        assessment_svc: AssessmentService = assessment_service,
        learner_svc: LearnerService = learner_service,
        journey_svc: JourneyService = journey_service,
        recommendation_svc: RecommendationService = recommendation_service,
        evidence_svc: EvidenceService = evidence_service,
        question_gen: QuestionGenerator = question_generator,
    ):
        self.session_repo = session_repo
        self.concept_repo = concept_repo
        self.journey_repo = journey_repo
        self.goal_repo = goal_repo
        self.rec_repo = rec_repo
        self.learner_repo = learner_repo
        self.assessment_svc = assessment_svc
        self.learner_svc = learner_svc
        self.journey_svc = journey_svc
        self.recommendation_svc = recommendation_svc
        self.evidence_svc = evidence_svc
        self.question_gen = question_gen

    async def create_session(self, user_id: str, request: SessionCreateRequest) -> SessionResponse:
        logger.info(f"Creating adaptive session for user {user_id}")

        # 1. Resolve recommendation context if provided
        rec_record = None
        if request.recommendation_id:
            rec_record = await self.rec_repo.get_by_id(request.recommendation_id)

        # 2. Determine session type
        session_type = request.session_type
        if not session_type and rec_record:
            try:
                session_type = SessionType(rec_record.action_type.value)
            except Exception:
                session_type = SessionType.LEARN
        elif not session_type:
            session_type = SessionType.LEARN

        # 3. Determine concept ID
        concept_id = request.concept_id
        if not concept_id and rec_record and rec_record.concept_id:
            concept_id = rec_record.concept_id

        # Fallback to active goal/node
        goal = None
        if request.goal_id:
            goal = await self.goal_repo.get_by_id(request.goal_id)
        if not goal:
            goal = await self.goal_repo.get_active_goal_for_user(user_id)

        if not concept_id and goal:
            journey = await self.journey_repo.get_by_goal_id(goal.id)
            if journey and journey.nodes:
                curr_node = next((n for n in journey.nodes if n.state == NodeState.CURRENT), journey.nodes[0])
                concept_id = curr_node.concept_id

        if not concept_id:
            concept_id = "concept_dart_async_and_streams"

        # 4. Resolve concept metadata
        concept = await self.concept_repo.get_by_id(concept_id)
        concept_name = concept.name if concept else concept_id.replace("concept_", "").replace("_", " ").title()
        concept_description = concept.description if concept else "Mastery of core invariant principles."

        # 5. Gather Learner state: weaknesses, misconceptions, level
        learner_state = await self.learner_svc.get_or_create_concept_state(user_id, concept_id)
        active_misconceptions = await self.learner_repo.list_misconceptions_for_concept(user_id, concept_id)
        misconception_tags = list(set(learner_state.misconception_tags + [m.tag for m in active_misconceptions]))

        known_weaknesses = []
        if learner_state.risk_score >= 50.0:
            known_weaknesses.append(f"High risk ({learner_state.risk_score})")
        if learner_state.retention_score < 50.0:
            known_weaknesses.append(f"Memory decay ({learner_state.retention_score})")

        learner_level = goal.current_level if goal else "intermediate"
        target_benchmark = goal.target_benchmark if goal else "Production Readiness"
        goal_title = goal.title if goal else "Software Engineering Mastery"

        # 6. Synthesize structured session steps via QuestionGenerator (no random quizzes)
        plan = await self.question_gen.generate_session_plan(
            goal_title=goal_title,
            target_benchmark=target_benchmark,
            concept_name=concept_name,
            concept_description=concept_description,
            learner_level=learner_level,
            known_weaknesses=known_weaknesses,
            misconceptions=misconception_tags,
            resource_context="Official documentation and architectural patterns",
            session_type=session_type.value,
        )

        session_id = f"sess_{uuid.uuid4().hex[:10]}"
        session_steps: List[SessionStep] = []
        for s in plan.steps:
            try:
                st = SessionStepType(s.step_type.upper())
            except Exception:
                st = SessionStepType.PRACTICE

            step = SessionStep(
                id=f"step_{uuid.uuid4().hex[:8]}",
                order=s.order,
                step_type=st,
                title=s.title,
                instruction=s.instruction,
                prompt=s.prompt,
                question_type=s.question_type,
                options=s.options,
                rubric_criteria=s.rubric_criteria,
                correct_answer=getattr(s, "correct_answer", "") or "",
                explanation=getattr(s, "explanation", "") or "",
            )
            session_steps.append(step)

        session = LearningSession(
            id=session_id,
            user_id=user_id,
            goal_id=goal.id if goal else None,
            concept_id=concept_id,
            session_type=session_type,
            status=SessionStatus.ACTIVE,
            recommendation_id=request.recommendation_id,
            steps=session_steps,
            metadata=request.metadata or {},
        )
        await self.session_repo.save(session)

        step_schemas = [
            SessionStepSchema(
                id=st.id,
                order=st.order,
                step_type=st.step_type,
                title=st.title,
                instruction=st.instruction,
                prompt=st.prompt,
                question_type=st.question_type,
                options=st.options,
                rubric_criteria=st.rubric_criteria,
                correct_answer=st.correct_answer,
                explanation=st.explanation,
                user_response=st.user_response,
                evaluation_score=st.evaluation_score,
                feedback=st.feedback,
            )
            for st in session.steps
        ]

        return SessionResponse(
            id=session.id,
            session_id=session.id,
            user_id=session.user_id,
            goal_id=session.goal_id,
            concept_id=session.concept_id,
            concept_title=concept_name,
            session_type=session.session_type,
            status=session.status,
            recommendation_id=session.recommendation_id,
            steps=step_schemas,
            started_at=session.started_at,
            completed_at=session.completed_at,
            score=session.score,
            evidence=[],
        )


    async def complete_session(
        self, user_id: str, session_id: str, request: SessionCompleteRequest
    ) -> SessionResponse:
        session = await self.session_repo.get_by_id(session_id)
        if not session:
            raise EntityNotFoundError("Session", session_id)

        # ----------------------------------------------------------------------
        # TRANSACTIONAL COMPLETION PIPELINE
        # 1. Collect and structure learner answers
        # 2. Evaluate performance against rubric & correct answers
        # 3. Create evidence & update Learner Twin
        # 4. Update misconceptions & retention
        # 5. Advance journey node if earned
        # 6. Synthesize next recommendation
        # ----------------------------------------------------------------------

        # Resolve concept metadata & learner state
        concept = await self.concept_repo.get_by_id(session.concept_id)
        concept_name = concept.name if concept else session.concept_id
        learner_state = await self.learner_svc.get_or_create_concept_state(user_id, session.concept_id)
        prior_mastery = learner_state.mastery_score
        prior_confidence = learner_state.confidence_score

        # 1. Collect step responses from request and model_extra (if raw dictionary was sent)
        step_responses = list(request.step_responses or [])
        if not step_responses and getattr(request, "model_extra", None):
            for k, v in request.model_extra.items():
                if v is not None and str(v).strip() and (k.startswith("step_") or any(s.id == k for s in session.steps)):
                    step_responses.append({"step_id": k, "response": str(v)})

        user_submission = request.user_submission
        if not user_submission and step_responses:
            user_submission = "\n".join([f"Step {r.get('step_id', '')}: {r.get('response', '')}" for r in step_responses if r.get('response')])

        # 2. EVALUATE PERFORMANCE against rubric
        eval_result = await self.assessment_svc.evaluate_learner_performance(
            concept_name=concept_name,
            session_type=session.session_type.value,
            submission=user_submission,
            prior_misconceptions=learner_state.misconception_tags,
            quiz_data={"quiz_results": request.quiz_results, "step_responses": step_responses},
            steps=session.steps,
        )

        # Update step records with evaluation results
        for st in session.steps:
            for se in eval_result.step_evaluations:
                if se.step_id == st.id:
                    st.user_response = se.user_answer
                    st.evaluation_score = 100.0 if se.is_correct else 0.0
                    st.feedback = se.explanation
                    break

        # 3. CREATE EVIDENCE
        ev_type = EvidenceType.PRACTICE
        stype = session.session_type
        if stype == SessionType.LEARN:
            ev_type = EvidenceType.ASSESSMENT
        elif stype == SessionType.PROVE:
            ev_type = EvidenceType.PROJECT
        elif stype == SessionType.TEACH:
            ev_type = EvidenceType.TEACH_BACK
        elif stype == SessionType.REVISE:
            ev_type = EvidenceType.RECALL
        elif stype == SessionType.REFLECT:
            ev_type = EvidenceType.EXPLANATION
        elif stype == SessionType.REMEDIATE:
            ev_type = EvidenceType.EXPLANATION

        evidence = await self.evidence_svc.record_evidence(
            user_id=user_id,
            concept_id=session.concept_id,
            evidence_type=ev_type,
            score=eval_result.score,
            feedback=eval_result.feedback,
            session_id=session.id,
            reasoning_score=eval_result.reasoning_score,
            transfer_score=eval_result.transfer_score,
            misconceptions_detected=eval_result.misconceptions_detected,
            self_confidence=request.self_reported_confidence,
        )

        # Refresh learner state after evidence update to calculate actual deltas
        refreshed_state = await self.learner_svc.get_or_create_concept_state(user_id, session.concept_id)
        mastery_delta = round(refreshed_state.mastery_score - prior_mastery, 1)
        confidence_delta = round(refreshed_state.confidence_score - prior_confidence, 1)

        # 4. UPDATE LEARNER CONCEPT STATE, MISCONCEPTIONS & RETENTION
        for resolved_tag in eval_result.resolved_misconceptions:
            if resolved_tag in refreshed_state.misconception_tags:
                refreshed_state.misconception_tags.remove(resolved_tag)
                logger.info(f"Resolved misconception '{resolved_tag}' for concept {session.concept_id}")

        active_miscs = await self.learner_repo.list_misconceptions_for_concept(user_id, session.concept_id)
        for m in active_miscs:
            if m.tag in eval_result.resolved_misconceptions:
                from app.domain.learner.models import MisconceptionStatus
                m.status = MisconceptionStatus.RESOLVED
                m.resolved_at = datetime.now(timezone.utc)
                await self.learner_repo.save_misconception(m)

        refreshed_state.risk_score = self.learner_svc.update_risk(
            refreshed_state.mastery_score, refreshed_state.retention_score, len(refreshed_state.misconception_tags)
        )
        await self.learner_repo.save_concept_state(refreshed_state)

        # Update session record
        session.status = SessionStatus.COMPLETED
        session.completed_at = datetime.now(timezone.utc)
        session.score = eval_result.score
        session.evidence.append(evidence)
        await self.session_repo.save(session)

        # 5. UPDATE JOURNEY (advance node, recalculate progress, unlock prerequisites)
        journey = None
        if session.goal_id:
            journey = await self.journey_repo.get_by_goal_id(session.goal_id)
        if not journey:
            active_goal = await self.goal_repo.get_active_goal_for_user(user_id)
            if active_goal:
                journey = await self.journey_repo.get_by_goal_id(active_goal.id)

        if journey:
            matching_node = next((n for n in journey.nodes if n.concept_id == session.concept_id), None)
            if matching_node and eval_result.score >= 60.0:
                await self.journey_svc.update_node_state(journey.id, matching_node.id, NodeState.COMPLETED)
            elif matching_node:
                await self.journey_svc.update_node_state(
                    journey.id, matching_node.id, matching_node.state, node_progress=int(eval_result.score)
                )

        # 6. CREATE NEXT RECOMMENDATION
        next_today_brief = await self.recommendation_svc.get_today_recommendation(user_id)
        next_rec = next_today_brief.recommended_action

        evidence_schemas = [
            EvidenceSchema(
                id=e.id,
                concept_id=e.concept_id,
                evidence_type=e.evidence_type,
                score=e.score,
                feedback=e.feedback,
                reasoning_score=e.reasoning_score,
                transfer_score=e.transfer_score,
                misconceptions_detected=e.misconceptions_detected,
                created_at=e.created_at,
            )
            for e in session.evidence
        ]

        step_schemas = [
            SessionStepSchema(
                id=st.id,
                order=st.order,
                step_type=st.step_type,
                title=st.title,
                instruction=st.instruction,
                prompt=st.prompt,
                question_type=st.question_type,
                options=st.options,
                rubric_criteria=st.rubric_criteria,
                correct_answer=st.correct_answer,
                explanation=st.explanation,
                user_response=st.user_response,
                evaluation_score=st.evaluation_score,
                feedback=st.feedback,
            )
            for st in session.steps
        ]

        step_eval_schemas = [
            StepEvaluationSchema(
                step_id=se.step_id or "",
                question=se.question or "",
                user_answer=se.user_answer or "",
                is_correct=se.is_correct,
                correct_answer=se.correct_answer or "",
                explanation=se.explanation or "",
            )
            for se in eval_result.step_evaluations
        ]

        return SessionResponse(
            id=session.id,
            session_id=session.id,
            user_id=session.user_id,
            goal_id=session.goal_id,
            concept_id=session.concept_id,
            concept_title=concept_name,
            session_type=session.session_type,
            status=session.status,
            recommendation_id=session.recommendation_id,
            steps=step_schemas,
            started_at=session.started_at,
            completed_at=session.completed_at,
            score=session.score,
            evidence=evidence_schemas,
            mastery_delta=mastery_delta,
            confidence_delta=confidence_delta,
            current_mastery=refreshed_state.mastery_score,
            current_confidence=refreshed_state.confidence_score,
            improvements=eval_result.improvements,
            focus_areas=eval_result.focus_areas,
            mentor_recommendation=next_today_brief.mentor_note or eval_result.feedback,
            accuracy_score=eval_result.accuracy_score,
            completeness_score=eval_result.completeness_score,
            reasoning_feedback=eval_result.feedback,
            identified_misconceptions=eval_result.misconceptions_detected,
            step_evaluations=step_eval_schemas,
            next_recommended_step=f"{next_rec.quick_action_label}: {next_rec.title}" if next_rec else None,
            next_recommendation=next_rec,
        )



session_service = SessionService()
