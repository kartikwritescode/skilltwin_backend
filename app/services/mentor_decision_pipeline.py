import uuid
from datetime import datetime, timezone, date
from typing import Optional, List, Dict, Any, Tuple
from app.domain.mentor.models import (
    ActionType,
    ActionRecommendation,
    RecommendationRecord,
)
from app.domain.journeys.models import NodeState
from app.repositories.goal_repository import GoalRepository, goal_repository
from app.repositories.journey_repository import JourneyRepository, journey_repository
from app.repositories.learner_repository import LearnerRepository, learner_repository
from app.repositories.session_repository import SessionRepository, session_repository
from app.repositories.concept_repository import ConceptRepository, concept_repository
from app.repositories.revision_repository import RevisionRepository, revision_repository
from app.repositories.recommendation_repository import RecommendationRepository, recommendation_repository
from app.services.retention_engine import RetentionEngine, retention_engine
from app.ai.orchestrator.context_builder import MentorContextBuilder, context_builder, MentorContext, PrerequisiteSummary
from app.ai.orchestrator.mentor_orchestrator import MentorOrchestrator
from app.ai.providers.factory import get_llm_provider
from app.schemas.mentor import ActionRecommendationSchema, MentorTodayResponse
from app.core.logging import logger


class MentorDecisionPipeline:
    """
    Unified 14-Step Mentor Decision Pipeline for SkillTwin.
    
    Orchestrates deterministic cognitive assessment and generative empathy:
    1. Load goal
    2. Load journey
    3. Load learner state
    4. Load recent evidence
    5. Load misconceptions
    6. Calculate retention risk
    7. Check prerequisites
    8. Evaluate deadline pressure
    9. Determine candidate actions (all 8 actions)
    10. Rank actions
    11. Select next best action
    12. Generate mentor explanation (LLM used for language, tone, empathy)
    13. Persist recommendation
    14. Return structured response
    """

    ALL_CANDIDATE_ACTIONS = [
        ActionType.LEARN,
        ActionType.REVISE,
        ActionType.PRACTICE,
        ActionType.PROVE,
        ActionType.TEACH,
        ActionType.REMEDIATE,
        ActionType.SKIP,
        ActionType.REFLECT,
    ]

    def __init__(
        self,
        goal_repo: GoalRepository = goal_repository,
        journey_repo: JourneyRepository = journey_repository,
        learner_repo: LearnerRepository = learner_repository,
        session_repo: SessionRepository = session_repository,
        concept_repo: ConceptRepository = concept_repository,
        revision_repo: RevisionRepository = revision_repository,
        rec_repo: RecommendationRepository = recommendation_repository,
        retention_eng: RetentionEngine = retention_engine,
        ctx_builder: MentorContextBuilder = context_builder,
        orchestrator: Optional[MentorOrchestrator] = None,
    ):
        self.goal_repo = goal_repo
        self.journey_repo = journey_repo
        self.learner_repo = learner_repo
        self.session_repo = session_repo
        self.concept_repo = concept_repo
        self.revision_repo = revision_repo
        self.rec_repo = rec_repo
        self.retention_eng = retention_eng
        self.ctx_builder = ctx_builder
        self.orchestrator = orchestrator or MentorOrchestrator(get_llm_provider())

    async def execute(self, user_id: str) -> MentorTodayResponse:
        logger.info(f"Executing 14-step MentorDecisionPipeline for user {user_id}")
        now = datetime.now(timezone.utc)

        # ----------------------------------------------------------------------
        # STEP 1: LOAD GOAL
        # ----------------------------------------------------------------------
        goal = await self.goal_repo.get_active_goal_for_user(user_id)

        # ----------------------------------------------------------------------
        # STEP 2: LOAD JOURNEY
        # ----------------------------------------------------------------------
        journey = await self.journey_repo.get_by_goal_id(goal.id) if goal else None

        current_node = None
        current_concept_id = None
        if journey and journey.nodes:
            current_node = next((n for n in journey.nodes if n.state == NodeState.CURRENT), None)
            if not current_node:
                current_node = next((n for n in journey.nodes if n.state == NodeState.AVAILABLE), None)
            if current_node:
                current_concept_id = current_node.concept_id

        # ----------------------------------------------------------------------
        # STEP 3: LOAD LEARNER STATE
        # ----------------------------------------------------------------------
        concept_state = None
        if current_concept_id:
            concept_state = await self.learner_repo.get_concept_state(user_id, current_concept_id)

        mastery_score = concept_state.mastery_score if concept_state else 0.0
        confidence_score = concept_state.confidence_score if concept_state else 0.0
        evidence_count = concept_state.evidence_count if concept_state else 0

        # ----------------------------------------------------------------------
        # STEP 4: LOAD RECENT EVIDENCE
        # ----------------------------------------------------------------------
        recent_sessions = await self.session_repo.list_by_user_id(user_id)
        recent_proofs = []
        for s in recent_sessions[-3:]:
            for e in s.evidence:
                recent_proofs.append(e)

        # ----------------------------------------------------------------------
        # STEP 5: LOAD MISCONCEPTIONS
        # ----------------------------------------------------------------------
        active_miscs = []
        if current_concept_id:
            active_miscs = await self.learner_repo.list_misconceptions_for_concept(
                user_id, current_concept_id, active_only=True
            )
        misc_tags = [m.tag for m in active_miscs]

        # ----------------------------------------------------------------------
        # STEP 6: CALCULATE RETENTION RISK
        # ----------------------------------------------------------------------
        due_revisions = await self.revision_repo.list_due_for_user(user_id)
        top_due_retention = due_revisions[0] if due_revisions else None
        retention_risk = "low"
        if top_due_retention:
            retention_risk = top_due_retention.retention_risk

        # ----------------------------------------------------------------------
        # STEP 7: CHECK PREREQUISITES
        # ----------------------------------------------------------------------
        prereq_deficits: List[Dict[str, Any]] = []
        if journey and current_node:
            for pid in current_node.prerequisites:
                pnode = next((n for n in journey.nodes if n.id == pid), None)
                if pnode:
                    pstate = await self.learner_repo.get_concept_state(user_id, pnode.concept_id)
                    pmastery = pstate.mastery_score if pstate else 0.0
                    is_sat = pnode.state in (NodeState.COMPLETED, NodeState.SKIPPED) and pmastery >= 60.0
                    if not is_sat:
                        prereq_deficits.append({
                            "node_id": pnode.id,
                            "concept_id": pnode.concept_id,
                            "title": pnode.title,
                            "mastery": pmastery,
                        })

        # ----------------------------------------------------------------------
        # STEP 8: EVALUATE DEADLINE PRESSURE
        # ----------------------------------------------------------------------
        deadline_pressure = "normal"
        if goal and goal.deadline:
            try:
                if isinstance(goal.deadline, str):
                    deadline_dt = datetime.fromisoformat(goal.deadline)
                elif isinstance(goal.deadline, datetime):
                    deadline_dt = goal.deadline
                elif isinstance(goal.deadline, date):
                    deadline_dt = datetime.combine(goal.deadline, datetime.min.time())
                else:
                    deadline_dt = now + timedelta(days=30)

                if deadline_dt.tzinfo is None:
                    deadline_dt = deadline_dt.replace(tzinfo=timezone.utc)

                days_left = max(0.1, (deadline_dt - now).total_seconds() / 86400.0)
                daily_budget = goal.daily_minutes or 30
                available_time_mins = days_left * daily_budget

                remaining_journey_mins = 0
                if journey and journey.nodes:
                    for n in journey.nodes:
                        if n.state not in (NodeState.COMPLETED, NodeState.SKIPPED):
                            remaining_journey_mins += n.estimated_minutes

                if available_time_mins < remaining_journey_mins:
                    deadline_pressure = "high"
                elif available_time_mins < remaining_journey_mins * 1.4:
                    deadline_pressure = "medium"
                else:
                    deadline_pressure = "low"
            except Exception as e:
                logger.debug(f"Could not parse deadline for pressure calculation: {e}")
                deadline_pressure = "normal"

        # ----------------------------------------------------------------------
        # STEP 9: DETERMINE CANDIDATE ACTIONS & SUITABILITY SCORES
        # ----------------------------------------------------------------------
        scores: Dict[ActionType, float] = {}
        target_concept_map: Dict[ActionType, str] = {}
        rule_map: Dict[ActionType, str] = {}

        # If no active goal
        if not goal:
            for action in self.ALL_CANDIDATE_ACTIONS:
                scores[action] = 10.0
            scores[ActionType.REFLECT] = 100.0
            target_concept_map[ActionType.REFLECT] = "goal_onboarding"
            rule_map[ActionType.REFLECT] = "NO_ACTIVE_GOAL"
        else:
            # 1. REMEDIATE
            if prereq_deficits:
                scores[ActionType.REMEDIATE] = 98.0
                target_concept_map[ActionType.REMEDIATE] = prereq_deficits[0]["concept_id"]
                rule_map[ActionType.REMEDIATE] = f"PREREQUISITE_DEFICIT: {prereq_deficits[0]['title']}"
            elif misc_tags:
                scores[ActionType.REMEDIATE] = 95.0
                target_concept_map[ActionType.REMEDIATE] = current_concept_id or "concept_active"
                rule_map[ActionType.REMEDIATE] = f"ACTIVE_MISCONCEPTIONS: {', '.join(misc_tags)}"
            else:
                scores[ActionType.REMEDIATE] = 15.0
                target_concept_map[ActionType.REMEDIATE] = current_concept_id or "concept_active"
                rule_map[ActionType.REMEDIATE] = "NO_CRITICAL_GAPS"

            # 2. REVISE
            if top_due_retention and (top_due_retention.retention_risk == "high" or top_due_retention.is_high_priority):
                scores[ActionType.REVISE] = 92.0
                target_concept_map[ActionType.REVISE] = top_due_retention.concept_id
                rule_map[ActionType.REVISE] = "CRITICAL_RETENTION_DECAY"
            elif top_due_retention:
                scores[ActionType.REVISE] = 72.0
                target_concept_map[ActionType.REVISE] = top_due_retention.concept_id
                rule_map[ActionType.REVISE] = "SCHEDULED_RETRIEVAL"
            else:
                scores[ActionType.REVISE] = 20.0
                target_concept_map[ActionType.REVISE] = current_concept_id or "concept_active"
                rule_map[ActionType.REVISE] = "RETENTION_STABLE"

            # 3. PROVE
            if mastery_score >= 75.0 and evidence_count < 2:
                scores[ActionType.PROVE] = 88.0
                target_concept_map[ActionType.PROVE] = current_concept_id or "concept_active"
                rule_map[ActionType.PROVE] = "UNVERIFIED_HIGH_MASTERY"
            else:
                scores[ActionType.PROVE] = 30.0
                target_concept_map[ActionType.PROVE] = current_concept_id or "concept_active"
                rule_map[ActionType.PROVE] = "MASTERY_CALIBRATED"

            # 4. TEACH (Feynman Technique)
            if mastery_score >= 75.0 and evidence_count >= 2:
                scores[ActionType.TEACH] = 86.0
                target_concept_map[ActionType.TEACH] = current_concept_id or "concept_active"
                rule_map[ActionType.TEACH] = "SOLIDIFY_DEEP_MENTAL_MODEL"
            else:
                scores[ActionType.TEACH] = 25.0
                target_concept_map[ActionType.TEACH] = current_concept_id or "concept_active"
                rule_map[ActionType.TEACH] = "FOUNDATIONS_PENDING"

            # 5. SKIP
            if mastery_score >= 90.0 and confidence_score >= 85.0 and evidence_count >= 2:
                boost = 10.0 if deadline_pressure == "high" else 0.0
                scores[ActionType.SKIP] = 85.0 + boost
                target_concept_map[ActionType.SKIP] = current_concept_id or "concept_active"
                rule_map[ActionType.SKIP] = "VERIFIED_ADVANCED_MASTERY"
            elif deadline_pressure == "high" and mastery_score >= 80.0:
                scores[ActionType.SKIP] = 78.0
                target_concept_map[ActionType.SKIP] = current_concept_id or "concept_active"
                rule_map[ActionType.SKIP] = "DEADLINE_PRESSURE_ACCELERATION"
            else:
                scores[ActionType.SKIP] = 10.0
                target_concept_map[ActionType.SKIP] = current_concept_id or "concept_active"
                rule_map[ActionType.SKIP] = "MASTERY_IN_PROGRESS"

            # 6. PRACTICE
            if 40.0 <= mastery_score < 75.0:
                scores[ActionType.PRACTICE] = 82.0
                target_concept_map[ActionType.PRACTICE] = current_concept_id or "concept_active"
                rule_map[ActionType.PRACTICE] = "ACTIVE_APPLICATION_PRACTICE"
            else:
                scores[ActionType.PRACTICE] = 40.0
                target_concept_map[ActionType.PRACTICE] = current_concept_id or "concept_active"
                rule_map[ActionType.PRACTICE] = "CONCEPT_BASELINE"

            # 7. LEARN
            if mastery_score < 40.0:
                scores[ActionType.LEARN] = 80.0
                target_concept_map[ActionType.LEARN] = current_concept_id or "concept_active"
                rule_map[ActionType.LEARN] = "NEW_ROADMAP_MILESTONE"
            else:
                scores[ActionType.LEARN] = 35.0
                target_concept_map[ActionType.LEARN] = current_concept_id or "concept_active"
                rule_map[ActionType.LEARN] = "MILESTONE_STARTED"

            # 8. REFLECT
            if deadline_pressure == "high":
                scores[ActionType.REFLECT] = 60.0
                target_concept_map[ActionType.REFLECT] = "curriculum_review"
                rule_map[ActionType.REFLECT] = "PACE_REALIGNMENT"
            else:
                scores[ActionType.REFLECT] = 20.0
                target_concept_map[ActionType.REFLECT] = "weekly_review"
                rule_map[ActionType.REFLECT] = "PERIODIC_REFLECTION"

        # ----------------------------------------------------------------------
        # STEP 10: RANK ACTIONS (Deterministic Scoring Matrix)
        # ----------------------------------------------------------------------
        ranked_candidates = sorted(
            [
                {
                    "action_type": act.value,
                    "score": round(scores[act], 1),
                    "target_concept_id": target_concept_map.get(act),
                    "rule": rule_map.get(act, "DEFAULT"),
                }
                for act in self.ALL_CANDIDATE_ACTIONS
            ],
            key=lambda x: x["score"],
            reverse=True,
        )

        # ----------------------------------------------------------------------
        # STEP 11: SELECT NEXT BEST ACTION
        # ----------------------------------------------------------------------
        top_candidate = ranked_candidates[0]
        selected_action_type = ActionType(top_candidate["action_type"])
        selected_concept_id = top_candidate["target_concept_id"]
        selected_rule = top_candidate["rule"]

        # Build selective context for generative explanation
        context = await self.ctx_builder.build_context(user_id)

        # ----------------------------------------------------------------------
        # STEP 12: GENERATE MENTOR EXPLANATION (LLM for empathy, pedagogical rationale)
        # ----------------------------------------------------------------------
        structured_ai_out = await self.orchestrator.synthesize_recommendation(
            context=context,
            rule_hint=selected_action_type,
        )

        # ----------------------------------------------------------------------
        # STEP 13: PERSIST RECOMMENDATION
        # ----------------------------------------------------------------------
        rec_record = RecommendationRecord(
            id=f"rec_{uuid.uuid4().hex[:10]}",
            user_id=user_id,
            goal_id=goal.id if goal else None,
            concept_id=selected_concept_id,
            action_type=selected_action_type,
            title=structured_ai_out.title,
            reason=structured_ai_out.reason,
            estimated_minutes=structured_ai_out.estimated_minutes,
            confidence=structured_ai_out.confidence,
            rule_matched=selected_rule,
        )
        await self.rec_repo.save(rec_record)

        # ----------------------------------------------------------------------
        # STEP 14: RETURN STRUCTURED RESPONSE
        # ----------------------------------------------------------------------
        rec_schema = ActionRecommendationSchema(
            action_type=selected_action_type,
            title=rec_record.title,
            reason=rec_record.reason,
            estimated_minutes=rec_record.estimated_minutes,
            concept_id=selected_concept_id,
            node_id=current_node.id if current_node else None,
            priority=1,
            quick_action_label=f"Start {selected_action_type.value.capitalize()}",
        )

        # Alternative actions (rank 2 and 3)
        alt_actions = []
        for alt in ranked_candidates[1:3]:
            alt_act = ActionType(alt["action_type"])
            alt_actions.append(
                ActionRecommendationSchema(
                    action_type=alt_act,
                    title=f"Alternative: {alt_act.value.capitalize()}",
                    reason=f"Ranked #{len(alt_actions)+2} based on {alt['rule']}",
                    estimated_minutes=15,
                    concept_id=alt["target_concept_id"],
                    node_id=current_node.id if current_node else None,
                    priority=len(alt_actions) + 2,
                    quick_action_label=f"{alt_act.value.capitalize()} Now",
                )
            )

        greeting = (
            f"Welcome back! Let's focus on your {goal.title} journey."
            if goal else "Welcome to SkillTwin!"
        )

        daily_checklist = [
            f"{rec_schema.quick_action_label}: {rec_schema.title} ({rec_schema.estimated_minutes} min)",
            f"Pace status: {deadline_pressure.capitalize()} deadline pressure",
        ]

        logger.info(
            f"Pipeline Complete: {selected_action_type.value} on {selected_concept_id} (Score: {top_candidate['score']})"
        )

        return MentorTodayResponse(
            greeting=greeting,
            mentor_note=rec_record.reason,
            current_goal_title=goal.title if goal else None,
            current_goal_progress=journey.progress if journey else 0.0,
            recommended_action=rec_schema,
            alternative_actions=alt_actions,
            candidate_rankings=ranked_candidates,
            deadline_pressure=deadline_pressure,
            pipeline_steps_executed=14,
            daily_checklist=daily_checklist,
        )


mentor_decision_pipeline = MentorDecisionPipeline()
