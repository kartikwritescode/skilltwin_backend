import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple
from app.repositories.concept_repository import ConceptRepository, concept_repository
from app.repositories.journey_repository import JourneyRepository, journey_repository
from app.repositories.goal_repository import GoalRepository, goal_repository
from app.repositories.learner_repository import LearnerRepository, learner_repository
from app.repositories.session_repository import SessionRepository, session_repository
from app.services.learner_service import LearnerService, learner_service
from app.services.resource_service import ResourceService, resource_service
from app.domain.journeys.models import NodeState
from app.ai.providers.base import LLMProvider
from app.ai.providers.factory import get_llm_provider
from app.ai.schemas.ai_schemas import PersonalizedStudyNotesAIOutput
from app.ai.prompts.templates import PERSONALIZED_NOTES_PROMPT
from app.schemas.knowledge import (
    MaintenanceAction,
    ConceptMaintenanceItem,
    KnowledgeMaintenanceResponse,
    PersonalizedStudyNotesResponse,
)
from app.core.exceptions import EntityNotFoundError
from app.core.logging import logger


class KnowledgeMaintenanceService:
    def __init__(
        self,
        concept_repo: ConceptRepository = concept_repository,
        journey_repo: JourneyRepository = journey_repository,
        goal_repo: GoalRepository = goal_repository,
        learner_repo: LearnerRepository = learner_repository,
        session_repo: SessionRepository = session_repository,
        learner_svc: LearnerService = learner_service,
        resource_svc: ResourceService = resource_service,
        llm_provider: Optional[LLMProvider] = None,
    ):
        self.concept_repo = concept_repo
        self.journey_repo = journey_repo
        self.goal_repo = goal_repo
        self.learner_repo = learner_repo
        self.session_repo = session_repo
        self.learner_svc = learner_svc
        self.resource_svc = resource_svc
        self.llm_provider = llm_provider or get_llm_provider()
        self._notes_cache: Dict[str, Tuple[PersonalizedStudyNotesAIOutput, datetime]] = {}

    async def get_maintenance_overview(self, user_id: str) -> KnowledgeMaintenanceResponse:
        logger.info(f"Computing knowledge maintenance posture for user {user_id}")

        all_concepts = await self.concept_repo.list_all()
        user_states = await self.learner_repo.list_states_for_user(user_id)
        state_map = {s.concept_id: s for s in user_states}

        active_goal = await self.goal_repo.get_active_goal_for_user(user_id)
        journey = await self.journey_repo.get_by_goal_id(active_goal.id) if active_goal else None

        node_map = {}
        if journey and journey.nodes:
            for n in journey.nodes:
                node_map[n.concept_id] = n

        items: List[ConceptMaintenanceItem] = []
        breakdown = {action.value: 0 for action in MaintenanceAction}

        for concept in all_concepts:
            state = state_map.get(concept.id)
            mastery = state.mastery_score if state else 0.0
            retention = state.retention_score if state else 100.0
            misconceptions = state.misconception_tags if state else []
            evidence_count = state.evidence_count if state else 0

            journey_node = node_map.get(concept.id)
            is_goal_relevant = journey_node is not None
            journey_pos = journey_node.state.value if journey_node else "NOT_ON_PATH"

            action, priority, reason = self._classify_maintenance_posture(
                concept=concept,
                mastery=mastery,
                retention=retention,
                misconceptions=misconceptions,
                evidence_count=evidence_count,
                journey_node=journey_node,
                is_goal_relevant=is_goal_relevant,
            )

            breakdown[action.value] += 1
            items.append(
                ConceptMaintenanceItem(
                    concept_id=concept.id,
                    concept_name=concept.name,
                    action=action,
                    priority=priority,
                    reason=reason,
                    mastery_score=mastery,
                    retention_score=retention,
                    misconceptions=misconceptions,
                    journey_position=journey_pos,
                    is_goal_relevant=is_goal_relevant,
                    recommended_time_minutes=15 if action in (MaintenanceAction.FIX, MaintenanceAction.REVISE) else 20,
                )
            )

        items.sort(key=lambda x: x.priority)

        return KnowledgeMaintenanceResponse(
            user_id=user_id,
            generated_at=datetime.now(timezone.utc),
            total_concepts=len(items),
            breakdown=breakdown,
            items=items,
        )

    def _classify_maintenance_posture(
        self,
        concept,
        mastery: float,
        retention: float,
        misconceptions: List[str],
        evidence_count: int,
        journey_node,
        is_goal_relevant: bool,
    ) -> Tuple[MaintenanceAction, int, str]:
        # Rule 1: Active Misconceptions -> FIX (Priority 1)
        if misconceptions:
            return (
                MaintenanceAction.FIX,
                1,
                f"Active misconception detected: {', '.join(misconceptions)}. Immediate correction required.",
            )
        if is_goal_relevant and journey_node and journey_node.is_remediation and journey_node.state == NodeState.CURRENT:
            return (
                MaintenanceAction.FIX,
                1,
                "Remediation node active on critical path. Needs focused intervention.",
            )

        # Rule 2: Decayed Retention -> REVISE (Priority 2)
        if evidence_count > 0 and (retention < 50.0 or (mastery >= 50.0 and retention < 65.0)):
            return (
                MaintenanceAction.REVISE,
                2,
                f"Memory retention decay reached threshold ({retention:.1f}%). Retrieval practice needed.",
            )

        # Rule 3: Immediate Next in Active Journey -> LEARN_NEXT (Priority 3)
        if is_goal_relevant and journey_node and journey_node.state in (NodeState.CURRENT, NodeState.AVAILABLE):
            if mastery < 60.0:
                return (
                    MaintenanceAction.LEARN_NEXT,
                    3,
                    f"Current milestone node on journey ('{journey_node.phase}' phase). Build core invariants.",
                )

        # Rule 4: Stable, Verified Mastery -> KEEP (Priority 4)
        if mastery >= 75.0 and retention >= 70.0:
            return (
                MaintenanceAction.KEEP,
                4,
                f"Demonstrated stable mastery ({mastery:.1f}%). No intervention needed today.",
            )

        # Rule 5: Locked downstream or not on path -> DEPRIORITIZE (Priority 5)
        if is_goal_relevant and journey_node and journey_node.state == NodeState.LOCKED:
            return (
                MaintenanceAction.DEPRIORITIZE,
                5,
                "Node locked behind unsatisfied prerequisites. Focus on upstream milestones first.",
            )

        if not is_goal_relevant:
            return (
                MaintenanceAction.DEPRIORITIZE,
                5,
                "Concept outside active goal focus area. Preserved in background.",
            )

        return (
            MaintenanceAction.KEEP,
            4,
            "Stable baseline understanding. Maintain current trajectory.",
        )

    async def generate_personalized_notes(
        self,
        user_id: str,
        concept_id: str,
        force_regenerate: bool = False,
    ) -> PersonalizedStudyNotesResponse:
        logger.info(f"Generating personalized notes for user {user_id}, concept {concept_id}")

        concept = await self.concept_repo.get_by_id(concept_id)
        if not concept:
            raise EntityNotFoundError("Concept", concept_id)

        learner_state = await self.learner_svc.get_or_create_concept_state(user_id, concept_id)
        active_goal = await self.goal_repo.get_active_goal_for_user(user_id)

        # Check Cognitive State Cache
        cache_key = f"{user_id}:{concept_id}:{learner_state.evidence_count}:{len(learner_state.misconception_tags)}"
        if not force_regenerate and cache_key in self._notes_cache:
            cached_output, cached_time = self._notes_cache[cache_key]
            logger.info(f"Returning cached personalized notes for {concept_id}")
            return PersonalizedStudyNotesResponse(
                concept_id=concept_id,
                title=cached_output.title,
                summary=cached_output.summary,
                key_points=cached_output.key_points,
                your_weakness=cached_output.your_weakness,
                remember_this=cached_output.remember_this,
                next_action=cached_output.next_action,
                cached=True,
                generated_at=cached_time,
            )

        # 1. Retrieve RAG Source Chunks
        rag_chunks = await self.resource_svc.retrieve_relevant_chunks(
            user_id=user_id,
            concept_id=concept_id,
            query=concept.name,
            top_k=3,
        )
        source_chunks_text = (
            "\n---\n".join([f"[{c.resource_title}]: {c.content}" for c in rag_chunks])
            if rag_chunks else "Authoritative standard architecture documentation."
        )

        # 2. Gather previous explanations and feedback
        user_sessions = await self.session_repo.list_by_user_id(user_id)
        past_explanations = []
        for s in user_sessions:
            if s.concept_id == concept_id:
                for e in s.evidence:
                    if e.feedback:
                        past_explanations.append(f"Feedback: {e.feedback} (Score: {e.score})")

        prev_exp_text = "\n".join(past_explanations[:3]) if past_explanations else "No previous submissions logged yet."
        known_misc_text = ", ".join(learner_state.misconception_tags) if learner_state.misconception_tags else "None active"

        # 3. Prompt Structured LLM
        prompt = PERSONALIZED_NOTES_PROMPT.format(
            goal_title=active_goal.title if active_goal else "Software Engineering Mastery",
            concept_name=concept.name,
            concept_description=concept.description,
            source_chunks=source_chunks_text,
            mastery_score=learner_state.mastery_score,
            retention_score=learner_state.retention_score,
            known_misconceptions=known_misc_text,
            previous_explanations=prev_exp_text,
        )

        ai_output = await self.llm_provider.generate_structured(
            prompt=prompt,
            response_schema=PersonalizedStudyNotesAIOutput,
            system_prompt="You are SkillTwin's personal cognitive tutor and memory architect."
        )

        now = datetime.now(timezone.utc)
        self._notes_cache[cache_key] = (ai_output, now)

        return PersonalizedStudyNotesResponse(
            concept_id=concept_id,
            title=ai_output.title,
            summary=ai_output.summary,
            key_points=ai_output.key_points,
            your_weakness=ai_output.your_weakness,
            remember_this=ai_output.remember_this,
            next_action=ai_output.next_action,
            cached=False,
            generated_at=now,
        )


knowledge_maintenance_service = KnowledgeMaintenanceService()
