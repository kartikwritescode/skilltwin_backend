from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
from app.repositories.goal_repository import GoalRepository, goal_repository
from app.repositories.journey_repository import JourneyRepository, journey_repository
from app.repositories.learner_repository import LearnerRepository, learner_repository
from app.repositories.concept_repository import ConceptRepository, concept_repository
from app.repositories.revision_repository import RevisionRepository, revision_repository
from app.repositories.session_repository import SessionRepository, session_repository
from app.domain.journeys.models import NodeState
from app.core.logging import logger


@dataclass
class PrerequisiteSummary:
    node_id: str
    concept_id: str
    title: str
    mastery: float
    is_satisfied: bool


@dataclass
class MentorContext:
    user_id: str
    goal_id: Optional[str] = None
    goal_title: Optional[str] = None
    target_level: Optional[str] = None
    goal_progress: int = 0
    daily_minutes: int = 30
    current_module: Optional[str] = None
    current_node_id: Optional[str] = None
    current_node_title: Optional[str] = None
    current_concept_id: Optional[str] = None
    current_concept_mastery: float = 0.0
    current_concept_confidence: float = 0.0
    current_evidence_count: int = 0
    current_key_concepts: List[str] = field(default_factory=list)
    prerequisites: List[PrerequisiteSummary] = field(default_factory=list)
    active_misconceptions: List[str] = field(default_factory=list)
    due_retention_items: List[Dict[str, Any]] = field(default_factory=list)
    recent_session_proofs: List[Dict[str, Any]] = field(default_factory=list)

    def to_rag_dossier(self) -> str:
        """
        Formats an ultra-compact, high-density RAG context block (<120 tokens).
        Guarantees zero-drift personalization at minimal token expenditure.
        """
        kc_str = ", ".join(self.current_key_concepts[:5]) if self.current_key_concepts else "Core invariants"
        misc_str = ", ".join(self.active_misconceptions[:2]) if self.active_misconceptions else "None detected"
        return f"""
[LEARNER RAG DOSSIER]
Active Goal: {self.goal_title or 'General Mastery'} ({self.target_level or 'Beginner'}) | Overall Progress: {self.goal_progress}%
Current Module: {self.current_module or 'Core Foundations'}
Active Topic Milestone: {self.current_node_title or 'General Practice'} (Current Mastery: {int(self.current_concept_mastery)}%)
Target Key Concepts: {kc_str}
Known Cognitive Gaps: {misc_str}
Daily Budget: {self.daily_minutes} mins/day
""".strip()

    def to_llm_prompt(self) -> str:
        """Formats tightly budgeted, token-efficient context for the LLM."""
        prereq_lines = "\n".join(
            f"- {p.title} (Mastery: {p.mastery}%, Satisfied: {p.is_satisfied})"
            for p in self.prerequisites
        ) or "None (Foundational node)"

        misc_lines = ", ".join(self.active_misconceptions) or "None detected"

        retention_lines = "\n".join(
            f"- {item['concept_name']} (Risk: {item['retention_risk']}, Due: {item['interval_days']}d interval)"
            for item in self.due_retention_items
        ) or "None currently overdue"

        recent_lines = "\n".join(
            f"- Concept {e['concept_id']}: Score {e['score']} ({e['feedback'][:60]}...)"
            for e in self.recent_session_proofs
        ) or "No recent session history"

        return f"""
TARGET GOAL:
Title: {self.goal_title or 'General Practice'} ({self.target_level or 'Beginner'})
Overall Progress: {self.goal_progress}%
Daily Target: {self.daily_minutes} minutes

CURRENT MILESTONE NODE:
Module: {self.current_module or 'Foundations'}
Title: {self.current_node_title or 'None active'}
Current Concept Mastery: {self.current_concept_mastery}%
Key Concepts: {', '.join(self.current_key_concepts) or 'Foundational mechanics'}

PREREQUISITE STATE:
{prereq_lines}

ACTIVE MISCONCEPTIONS:
{misc_lines}

RETENTION / MEMORY DECAY RISKS:
{retention_lines}
""".strip()


class MentorContextBuilder:
    """
    Selects only the high-leverage context relevant to the next pedagogical intervention.
    Guarantees that database dumps or full histories are never sent to the LLM.
    """

    def __init__(
        self,
        goal_repo: GoalRepository = goal_repository,
        journey_repo: JourneyRepository = journey_repository,
        learner_repo: LearnerRepository = learner_repository,
        concept_repo: ConceptRepository = concept_repository,
        revision_repo: RevisionRepository = revision_repository,
        session_repo: SessionRepository = session_repository,
    ):
        self.goal_repo = goal_repo
        self.journey_repo = journey_repo
        self.learner_repo = learner_repo
        self.concept_repo = concept_repo
        self.revision_repo = revision_repo
        self.session_repo = session_repo

    async def build_context(
        self,
        user_id: str,
        client_context: Optional[Dict[str, Any]] = None,
    ) -> MentorContext:
        logger.debug(f"Building selective mentor context for learner: {user_id}")

        context = MentorContext(user_id=user_id)

        # 1. First attempt to load from live dynamic learning path
        try:
            from app.services.learning_path_service import learning_path_service
            path_resp = await learning_path_service.get_active_path_response(user_id)
            if path_resp:
                context.goal_id = path_resp.goal_id
                context.goal_title = path_resp.title
                context.target_level = path_resp.target_level
                context.goal_progress = int(path_resp.progress * 100)

                active_found = False
                for sec in path_resp.sections:
                    for top in sec.topics:
                        if top.status in ("learning", "in_progress"):
                            context.current_node_id = top.id
                            context.current_node_title = top.title
                            context.current_module = sec.title
                            context.current_key_concepts = top.key_concepts
                            context.current_concept_mastery = top.mastery_score
                            active_found = True
                            break
                    if active_found:
                        break

                if not active_found and path_resp.sections:
                    for sec in path_resp.sections:
                        for top in sec.topics:
                            if top.status != "completed":
                                context.current_node_id = top.id
                                context.current_node_title = top.title
                                context.current_module = sec.title
                                context.current_key_concepts = top.key_concepts
                                context.current_concept_mastery = top.mastery_score
                                active_found = True
                                break
                        if active_found:
                            break
        except Exception as e:
            logger.debug(f"Learning path lookup in context builder: {e}")

        # 2. Fetch active goal if not already populated
        active_goal = await self.goal_repo.get_active_goal_for_user(user_id)
        if active_goal:
            context.goal_id = context.goal_id or active_goal.id
            context.goal_title = context.goal_title or active_goal.title
            context.daily_minutes = active_goal.daily_minutes
            context.target_level = context.target_level or getattr(active_goal, "target_level", getattr(active_goal, "current_level", "Beginner"))

            # Fallback to in-memory journey if learning path was absent
            if not context.current_node_title:
                journey = await self.journey_repo.get_by_goal_id(active_goal.id)
                if journey:
                    context.goal_progress = journey.progress
                    current_node = next(
                        (n for n in journey.nodes if n.state == NodeState.CURRENT),
                        None
                    )
                    if not current_node:
                        current_node = next(
                            (n for n in journey.nodes if n.state == NodeState.AVAILABLE),
                            journey.nodes[0] if journey.nodes else None
                        )

                    if current_node:
                        context.current_node_id = current_node.id
                        context.current_node_title = current_node.title
                        context.current_concept_id = current_node.concept_id

                        state = await self.learner_repo.get_concept_state(user_id, current_node.concept_id)
                        if state:
                            context.current_concept_mastery = state.mastery
                            context.current_concept_confidence = state.confidence
                            context.current_evidence_count = state.evidence_count

                    # 4. Check prerequisites for current node
                    for prereq_node_id in current_node.prerequisites:
                        prereq_node = next((n for n in journey.nodes if n.id == prereq_node_id), None)
                        if prereq_node:
                            prereq_state = await self.learner_repo.get_concept_state(user_id, prereq_node.concept_id)
                            mastery = prereq_state.mastery if prereq_state else 0.0
                            is_sat = prereq_node.state in (NodeState.COMPLETED, NodeState.SKIPPED)
                            context.prerequisites.append(
                                PrerequisiteSummary(
                                    node_id=prereq_node.id,
                                    concept_id=prereq_node.concept_id,
                                    title=prereq_node.title,
                                    mastery=mastery,
                                    is_satisfied=is_sat,
                                )
                            )

                    # 5. Fetch active misconceptions for current concept
                    misconceptions = await self.learner_repo.list_misconceptions_for_concept(
                        user_id, current_node.concept_id, active_only=True
                    )
                    context.active_misconceptions = [m.tag for m in misconceptions]

        # 6. Fetch top due retention items (limit 2)
        due_revisions = await self.revision_repo.list_due_for_user(user_id)
        for item in due_revisions[:2]:
            context.due_retention_items.append({
                "concept_id": item.concept_id,
                "concept_name": item.concept_name,
                "retention_risk": item.retention_risk,
                "interval_days": item.interval,
                "priority_score": item.priority_score,
                "is_high_priority": item.is_high_priority,
            })

        # 7. Fetch recent session proofs (limit 3)
        all_sessions = await self.session_repo.list_by_user_id(user_id)
        for s in all_sessions[-3:]:
            for e in s.evidence:
                context.recent_session_proofs.append({
                    "concept_id": e.concept_id,
                    "score": e.score,
                    "feedback": e.feedback,
                })

        return context


context_builder = MentorContextBuilder()
