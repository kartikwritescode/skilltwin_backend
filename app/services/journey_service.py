import asyncio
import uuid
import math
from typing import Optional, List, Dict
from app.repositories.journey_repository import JourneyRepository, journey_repository
from app.repositories.concept_repository import ConceptRepository, concept_repository
from app.domain.journeys.models import (
    Journey,
    JourneyNode,
    JourneyEdge,
    NodeState,
    JourneyStatus,
    GenerationStatus,
)
from app.domain.concepts.models import Concept
from app.domain.goals.models import Goal
from app.ai.orchestrator.mentor_orchestrator import MentorOrchestrator
from app.ai.providers.factory import get_llm_provider
from app.schemas.journeys import JourneyResponse, JourneyNodeResponse
from app.core.exceptions import EntityNotFoundError
from app.core.logging import logger


class JourneyService:
    """
    Core Journey Engine:
    SkillTwin's roadmap is not a static course list. It is an adaptive, directed curriculum graph:
    Goal -> Phases -> Journey Nodes -> Concepts -> Prerequisites.

    Crucial Architectural Rule:
    LLM proposes concept, sequencing, prerequisites, and descriptions.
    The deterministic Journey Engine computes and enforces all node states, progress,
    prerequisite locks, skipping, and dynamic remediation insertion.
    """

    def __init__(
        self,
        journey_repo: JourneyRepository = journey_repository,
        concept_repo: ConceptRepository = concept_repository,
        orchestrator: Optional[MentorOrchestrator] = None,
    ):
        self.journey_repo = journey_repo
        self.concept_repo = concept_repo
        self.orchestrator = orchestrator or MentorOrchestrator(get_llm_provider())

    async def create_journey(self, goal: Goal) -> Journey:
        """Alias for creating initial journey record for a goal."""
        return await self.create_initial_journey(goal)

    async def create_initial_journey(self, goal: Goal) -> Journey:
        """Creates an initial journey record in PENDING state."""
        journey_id = f"jrn_{uuid.uuid4().hex[:12]}"
        journey = Journey(
            id=journey_id,
            goal_id=goal.id,
            user_id=goal.user_id,
            title=goal.title,
            progress=0,
            version=1,
            status=JourneyStatus.ACTIVE,
            generation_status=GenerationStatus.PENDING,
            nodes=[],
            edges=[],
        )
        await self.journey_repo.save(journey)
        logger.info(f"Initialized journey {journey_id} for goal '{goal.title}'")
        return journey

    def trigger_async_generation(self, journey_id: str, goal: Goal) -> asyncio.Task:
        """Launches the asynchronous AI journey generation workflow in the background."""
        return asyncio.create_task(self._generate_journey_nodes(journey_id, goal))

    async def _generate_journey_nodes(self, journey_id: str, goal: Goal) -> Optional[Journey]:
        journey = await self.journey_repo.get_by_id(journey_id)
        if not journey:
            logger.error(f"Cannot generate journey: record {journey_id} not found.")
            return None

        try:
            journey.generation_status = GenerationStatus.PROCESSING
            await self.journey_repo.save(journey)

            plan = await self.orchestrator.generate_journey_plan(
                goal_title=goal.title,
                goal_description=goal.description,
                current_level=goal.current_level,
                daily_minutes=goal.daily_minutes,
                target_benchmark=goal.target_benchmark,
            )

            journey_nodes: List[JourneyNode] = []
            order_to_id: Dict[int, str] = {}

            # Phase 1: Create nodes with assigned IDs
            for idx, n in enumerate(plan.nodes):
                node_id = f"node_{uuid.uuid4().hex[:8]}"
                order_to_id[n.order] = node_id

                concept_id = f"concept_{n.concept_name}"
                existing_concept = await self.concept_repo.get_by_id(concept_id)
                if not existing_concept:
                    await self.concept_repo.save(
                        Concept(
                            id=concept_id,
                            name=n.title,
                            description=n.description,
                            domain="Software Engineering",
                        )
                    )

                # Determine initial state: First node is CURRENT, rest start LOCKED
                initial_state = NodeState.CURRENT if idx == 0 else NodeState.LOCKED
                initial_prereqs = [order_to_id[n.order - 1]] if idx > 0 and (n.order - 1) in order_to_id else []

                pos_x = round(0.5 + 0.32 * math.sin(idx * 1.5), 3)
                pos_y = round(float(idx * 140.0), 1)

                journey_node = JourneyNode(
                    id=node_id,
                    journey_id=journey_id,
                    concept_id=concept_id,
                    title=n.title,
                    subtitle=n.description,
                    phase=n.phase,
                    order=idx + 1,
                    state=initial_state,
                    progress=0,
                    prerequisites=initial_prereqs,
                    estimated_minutes=n.estimated_minutes,
                    position_x=pos_x,
                    position_y=pos_y,
                )
                journey_nodes.append(journey_node)

            journey.title = goal.title
            journey.nodes = journey_nodes
            journey.generation_status = GenerationStatus.READY
            journey.generation_error = None
            self.calculate_progress(journey)

            await self.journey_repo.save(journey)
            logger.info(f"Journey {journey_id} generated successfully ({len(journey_nodes)} nodes).")
            return journey

        except Exception as e:
            logger.exception(f"Error generating journey {journey_id}: {e}")
            journey.generation_status = GenerationStatus.FAILED
            journey.generation_error = str(e)
            await self.journey_repo.save(journey)
            return journey

    # --------------------------------------------------------------------------
    # Deterministic State Management & Progress Engine
    # --------------------------------------------------------------------------

    def calculate_progress(self, journey: Journey) -> int:
        """
        Deterministically calculates overall journey completion progress (0 - 100).
        Nodes marked COMPLETED or SKIPPED contribute 100%.
        Other nodes contribute their partial progress (0 - 100).
        """
        if not journey.nodes:
            journey.progress = 0
            return 0

        total_points = 0
        for node in journey.nodes:
            if node.state in (NodeState.COMPLETED, NodeState.SKIPPED):
                total_points += 100
            else:
                total_points += max(0, min(100, node.progress))

        progress = int(round(total_points / len(journey.nodes)))
        journey.progress = max(0, min(100, progress))
        return journey.progress

    def unlock_nodes_when_prerequisites_satisfied(self, journey: Journey) -> bool:
        """
        Scans all LOCKED nodes. If all prerequisites are COMPLETED or SKIPPED,
        unlocks the node into AVAILABLE (or CURRENT if no node is currently active).
        Returns True if any node was unlocked.
        """
        completed_or_skipped_ids = {
            n.id for n in journey.nodes
            if n.state in (NodeState.COMPLETED, NodeState.SKIPPED)
        }

        has_current = any(n.state == NodeState.CURRENT for n in journey.nodes)
        state_changed = False

        for node in journey.nodes:
            if node.state == NodeState.LOCKED:
                # Check if every prerequisite is satisfied
                prereqs_met = all(prereq_id in completed_or_skipped_ids for prereq_id in node.prerequisites)
                if prereqs_met:
                    if not has_current:
                        node.state = NodeState.CURRENT
                        has_current = True
                    else:
                        node.state = NodeState.AVAILABLE
                    state_changed = True
                    logger.info(f"Node {node.id} ('{node.title}') unlocked -> {node.state.value}")

        return state_changed

    async def update_node_state(
        self,
        journey_id: str,
        node_id: str,
        new_state: NodeState,
        node_progress: Optional[int] = None,
    ) -> Journey:
        """
        Updates a node's state deterministically.
        If COMPLETED, unlocks downstream satisfied prerequisites and recalculates journey progress.
        """
        journey = await self.journey_repo.get_by_id(journey_id)
        if not journey:
            raise EntityNotFoundError("Journey", journey_id)

        target_node = next((n for n in journey.nodes if n.id == node_id), None)
        if not target_node:
            raise EntityNotFoundError("JourneyNode", node_id)

        target_node.state = new_state
        if new_state in (NodeState.COMPLETED, NodeState.SKIPPED):
            target_node.progress = 100
        elif node_progress is not None:
            target_node.progress = max(0, min(100, node_progress))

        logger.info(f"Updated node {node_id} state to {new_state.value} (progress: {target_node.progress}%)")

        # Cascade prerequisite unlocking
        self.unlock_nodes_when_prerequisites_satisfied(journey)
        self.calculate_progress(journey)

        await self.journey_repo.save(journey)
        return journey

    async def skip_mastered_nodes(
        self,
        journey: Journey,
        learner_mastery_map: Dict[str, float],
        mastery_threshold: float = 85.0,
    ) -> List[str]:
        """
        Automatically skips nodes whose corresponding concept mastery is already >= 85%.
        Cascades prerequisite unlocking downstream.
        """
        skipped_ids = []
        for node in journey.nodes:
            if node.state not in (NodeState.COMPLETED, NodeState.SKIPPED):
                concept_mastery = learner_mastery_map.get(node.concept_id, 0.0)
                if concept_mastery >= mastery_threshold:
                    node.state = NodeState.SKIPPED
                    node.progress = 100
                    skipped_ids.append(node.id)
                    logger.info(
                        f"Skipping mastered node {node.id} ('{node.title}') - concept mastery: {concept_mastery}%"
                    )

        if skipped_ids:
            self.unlock_nodes_when_prerequisites_satisfied(journey)
            self.calculate_progress(journey)
            await self.journey_repo.save(journey)

        return skipped_ids

    async def insert_remediation_nodes(
        self,
        journey_id: str,
        target_node_id: str,
        concept_id: str,
        title: str,
        subtitle: str,
        estimated_minutes: int = 15,
    ) -> JourneyNode:
        """
        Dynamically inserts a remediation node before the target node when a knowledge gap is detected.
        Sets target node to LOCKED and assigns the remediation node as its prerequisite.
        """
        journey = await self.journey_repo.get_by_id(journey_id)
        if not journey:
            raise EntityNotFoundError("Journey", journey_id)

        target_idx = None
        target_node = None
        for idx, n in enumerate(journey.nodes):
            if n.id == target_node_id:
                target_idx = idx
                target_node = n
                break

        if target_node is None or target_idx is None:
            raise EntityNotFoundError("JourneyNode", target_node_id)

        remed_id = f"remed_{uuid.uuid4().hex[:8]}"
        remediation_node = JourneyNode(
            id=remed_id,
            journey_id=journey_id,
            concept_id=concept_id,
            title=f"Remediation: {title}",
            subtitle=subtitle,
            phase=target_node.phase,
            order=target_node.order,
            state=NodeState.CURRENT,
            progress=0,
            estimated_minutes=estimated_minutes,
            prerequisites=list(target_node.prerequisites),
            is_remediation=True,
            position_x=round(target_node.position_x - 0.1, 3),
            position_y=round(target_node.position_y - 40.0, 1),
        )

        # Target node now requires remediation before it can proceed
        target_node.prerequisites = [remed_id]
        target_node.state = NodeState.LOCKED
        target_node.progress = 0

        # Insert remediation node before target node
        journey.nodes.insert(target_idx, remediation_node)

        # Re-index orders sequentially
        for i, node in enumerate(journey.nodes):
            node.order = i + 1

        self.calculate_progress(journey)
        await self.journey_repo.save(journey)

        logger.info(
            f"Inserted remediation node {remed_id} ('{title}') before target {target_node_id}"
        )
        return remediation_node

    async def get_journey(self, journey_id: str) -> JourneyResponse:
        journey = await self.journey_repo.get_by_id(journey_id)
        if not journey:
            raise EntityNotFoundError("Journey", journey_id)

        # Recalculate progress to guarantee fresh state
        self.calculate_progress(journey)

        node_responses = [
            JourneyNodeResponse(
                id=n.id,
                title=n.title,
                subtitle=n.subtitle,
                phase=n.phase,
                state=n.state,
                progress=n.progress,
                concept_id=n.concept_id,
                estimated_minutes=n.estimated_minutes,
                prerequisites=n.prerequisites,
                is_remediation=n.is_remediation,
                order=n.order,
                position_x=n.position_x,
                position_y=n.position_y,
            )
            for n in journey.nodes
        ]

        return JourneyResponse(
            id=journey.id,
            goal_id=journey.goal_id,
            title=journey.title or "Adaptive Mastery Roadmap",
            progress=journey.progress,
            nodes=node_responses,
            status=journey.status,
            generation_status=journey.generation_status,
            generation_error=journey.generation_error,
        )

    async def get_journey_by_goal(self, goal_id: str) -> Optional[Journey]:
        return await self.journey_repo.get_by_goal_id(goal_id)


journey_service = JourneyService()
