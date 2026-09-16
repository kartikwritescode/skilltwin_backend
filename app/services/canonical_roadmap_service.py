import os
import json
import math
import uuid
from typing import Optional, List, Dict, Tuple, Any
from app.core.logging import logger
from app.core.db_models import CanonicalRoadmapModel, CanonicalNodeModel
from app.repositories.canonical_roadmap_repository import (
    CanonicalRoadmapRepository,
    canonical_roadmap_repository,
)
from app.repositories.concept_repository import ConceptRepository, concept_repository
from app.domain.concepts.models import Concept
from app.domain.journeys.models import JourneyNode, NodeState
from app.services.embedding_service import EmbeddingService, embedding_service


class CanonicalRoadmapService:
    """
    Manages Canonical Technology Roadmaps, semantic similarity matching,
    and deterministic personalization for SkillTwin learners.
    """

    def __init__(
        self,
        canonical_repo: CanonicalRoadmapRepository = canonical_roadmap_repository,
        concept_repo: ConceptRepository = concept_repository,
        embedder: EmbeddingService = embedding_service,
    ):
        self.canonical_repo = canonical_repo
        self.concept_repo = concept_repo
        self.embedder = embedder
        self._fixtures_loaded = False

    async def ensure_fixtures_loaded(self, fixtures_dir: Optional[str] = None):
        """Loads canonical roadmaps from JSON fixture files into the repository and concept graph."""
        if self._fixtures_loaded and len(await self.canonical_repo.list_all()) > 0:
            return

        if not fixtures_dir:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            fixtures_dir = os.path.join(base_dir, "fixtures", "roadmaps")

        if not os.path.exists(fixtures_dir):
            logger.warning(f"Canonical roadmaps fixtures directory not found at: {fixtures_dir}")
            return

        json_files = [f for f in os.listdir(fixtures_dir) if f.endswith(".json")]
        logger.info(f"Loading {len(json_files)} canonical roadmap fixtures from {fixtures_dir}")

        for fname in json_files:
            file_path = os.path.join(fixtures_dir, fname)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                await self._load_single_fixture(data)
            except Exception as e:
                logger.error(f"Failed to load canonical roadmap fixture '{fname}': {e}", exc_info=True)

        self._fixtures_loaded = True

    async def _load_single_fixture(self, data: Dict[str, Any]) -> CanonicalRoadmapModel:
        slug = data.get("slug", "")
        roadmap_id = data.get("id") or f"roadmap_{slug or uuid.uuid4().hex[:8]}"
        title = data["title"]
        description = data.get("description", "")
        tags = data.get("tags", [])

        # Generate vector embedding for title, description, and tags
        embedding = data.get("embedding")
        if not embedding:
            text_to_embed = f"{title} {description} {' '.join(tags)}"
            embedding = await self.embedder.embed_query(text_to_embed)

        nodes_data = data.get("nodes", [])
        total_estimated_minutes = sum(n.get("estimated_minutes", 25) for n in nodes_data)

        roadmap = CanonicalRoadmapModel(
            id=roadmap_id,
            slug=data.get("slug", roadmap_id.replace("roadmap_", "")),
            title=title,
            description=description,
            domain=data.get("domain", "Software Engineering"),
            target_role=data.get("target_role"),
            difficulty_baseline=data.get("difficulty_baseline", "Beginner"),
            tags=tags,
            embedding=embedding,
            total_nodes=len(nodes_data),
            estimated_hours=round(total_estimated_minutes / 60.0, 1),
            is_active=True,
            version=data.get("version", 1),
        )

        canonical_nodes: List[CanonicalNodeModel] = []
        for n in nodes_data:
            cnode = CanonicalNodeModel(
                id=n.get("id", f"cnode_{uuid.uuid4().hex[:8]}"),
                roadmap_id=roadmap_id,
                concept_id=n["concept_id"],
                title=n["title"],
                subtitle=n.get("subtitle", ""),
                phase=n.get("phase", "Core"),
                tier=n.get("tier", "intermediate"),
                importance=n.get("importance", "essential"),
                difficulty=n.get("difficulty", "intermediate"),
                order=n.get("order", 1),
                estimated_minutes=n.get("estimated_minutes", 25),
                prerequisites=n.get("prerequisites", []),
                learning_objectives=n.get("learning_objectives", []),
                feynman_prompts=n.get("feynman_prompts", []),
                key_misconceptions=n.get("key_misconceptions", []),
                recommended_resources=n.get("recommended_resources", []),
            )
            canonical_nodes.append(cnode)

            # Ensure concept exists in ConceptRepository
            existing_concept = await self.concept_repo.get_by_id(n["concept_id"])
            if not existing_concept:
                await self.concept_repo.save(
                    Concept(
                        id=n["concept_id"],
                        name=n["title"],
                        description=n.get("subtitle", n["title"]),
                        domain=roadmap.domain,
                        difficulty_level=n.get("tier", "intermediate"),
                        prerequisites=n.get("prerequisites", []),
                    )
                )

        roadmap.nodes = canonical_nodes
        await self.canonical_repo.save(roadmap)
        return roadmap

    async def find_matching_roadmap(
        self,
        goal_title: str,
        goal_description: Optional[str] = None,
        target_benchmark: Optional[str] = None,
        threshold: float = 0.70,
    ) -> Optional[Tuple[CanonicalRoadmapModel, float]]:
        """
        Computes vector similarity between the user goal and canonical technology roadmaps.
        Returns the top matching roadmap and similarity score if similarity >= threshold, else None.
        """
        await self.ensure_fixtures_loaded()

        query_text = f"{goal_title} {goal_description or ''} {target_benchmark or ''}".strip()
        query_embedding = await self.embedder.embed_query(query_text)

        if not query_embedding:
            return None

        matches = await self.canonical_repo.similarity_search(
            query_embedding=query_embedding,
            query_text=query_text,
            top_k=1,
            threshold=threshold,
        )

        if matches:
            matched_roadmap, score = matches[0]
            logger.info(
                f"Canonical roadmap match: '{matched_roadmap.title}' "
                f"with similarity {score:.3f} (threshold: {threshold})"
            )
            return matched_roadmap, score

        logger.info(f"No canonical roadmap matched for '{goal_title}' above threshold {threshold}")
        return None

    def tailor_roadmap_to_nodes(
        self,
        roadmap: CanonicalRoadmapModel,
        journey_id: str,
        current_level: str = "Beginner",
        daily_minutes: int = 30,
        existing_masteries: Optional[Dict[str, float]] = None,
    ) -> List[JourneyNode]:
        """
        Deterministically personalizes a canonical roadmap into concrete JourneyNodes:
        1. Filters out niche or overwhelming topics for beginners or highly constrained schedules.
        2. Auto-credits nodes where the learner already has demonstrated mastery (>= 0.75).
        3. Scales estimated minutes based on daily available time.
        4. Calculates signature sine-wave coordinates (x, y) for the winding UI path.
        5. Sets initial states (CURRENT at the learner's knowledge boundary, AVAILABLE for unlocked foundations, LOCKED for future nodes).
        """
        existing_masteries = existing_masteries or {}
        level_normalized = current_level.strip().lower()

        sorted_cnodes = sorted(roadmap.nodes, key=lambda n: n.order)

        # Filter nodes based on user level so beginners are not overwhelmed by niche topics
        filtered_cnodes = []
        for cnode in sorted_cnodes:
            imp = getattr(cnode, "importance", "essential")
            diff = getattr(cnode, "difficulty", "intermediate")
            if level_normalized in ["beginner", "novice", "entry"]:
                if imp == "niche":
                    continue
                if daily_minutes < 25 and imp == "advanced" and diff in ["advanced", "expert"]:
                    continue
            filtered_cnodes.append(cnode)

        if not filtered_cnodes:
            filtered_cnodes = sorted_cnodes

        journey_nodes: List[JourneyNode] = []
        node_id_map: Dict[int, str] = {}

        # Phase 1: Pre-assign unique node IDs
        for idx, cnode in enumerate(filtered_cnodes):
            node_id = f"node_{uuid.uuid4().hex[:8]}"
            node_id_map[cnode.order] = node_id

        # Phase 2: Personalize each node
        current_assigned = False

        for idx, cnode in enumerate(filtered_cnodes):
            node_id = node_id_map[cnode.order]

            # Calculate prerequisite node IDs
            prereqs = [node_id_map[filtered_cnodes[idx - 1].order]] if idx > 0 else []

            # Learner Twin verified mastery check
            prior_mastery = existing_masteries.get(cnode.concept_id, 0.0)
            is_mastered_by_twin = prior_mastery >= 0.75

            if is_mastered_by_twin:
                state = NodeState.COMPLETED
                progress = 100
            elif not current_assigned:
                state = NodeState.CURRENT
                progress = 0
                current_assigned = True
            elif level_normalized in ["intermediate", "medium", "advanced", "expert"] and cnode.tier == "foundation":
                # For intermediate learners, foundational nodes are unlocked and available to explore or skip
                state = NodeState.AVAILABLE
                progress = 0
            else:
                state = NodeState.LOCKED
                progress = 0

            # Sine wave layout coordinates for Flutter winding path
            pos_x = round(0.5 + 0.32 * math.sin(idx * 1.5), 3)
            pos_y = round(float(idx * 140.0), 1)

            # Adapt estimated minutes to user commitment
            est_mins = cnode.estimated_minutes
            if daily_minutes < 20 and est_mins > 20:
                est_mins = 20

            metadata = {
                "tier": cnode.tier,
                "importance": getattr(cnode, "importance", "essential"),
                "difficulty": getattr(cnode, "difficulty", "intermediate"),
                "feynman_prompts": cnode.feynman_prompts,
                "key_misconceptions": cnode.key_misconceptions,
                "learning_objectives": cnode.learning_objectives,
                "canonical_node_id": cnode.id,
                "canonical_roadmap_id": roadmap.id,
            }

            j_node = JourneyNode(
                id=node_id,
                journey_id=journey_id,
                concept_id=cnode.concept_id,
                title=cnode.title,
                subtitle=cnode.subtitle or "",
                phase=cnode.phase,
                order=idx + 1,
                state=state,
                progress=progress,
                prerequisites=prereqs,
                estimated_minutes=est_mins,
                position_x=pos_x,
                position_y=pos_y,
                metadata=metadata,
            )
            journey_nodes.append(j_node)

        # In case all nodes were marked completed by level, set the last node as CURRENT
        if not current_assigned and journey_nodes:
            journey_nodes[-1].state = NodeState.CURRENT
            journey_nodes[-1].progress = 0

        return journey_nodes

    def tailor_curriculum_for_goal(
        self,
        roadmap: CanonicalRoadmapModel,
        target_level: str = "Intermediate",
        daily_minutes: int = 30,
        deadline_days: int = 60,
        current_knowledge: Optional[List[str]] = None,
        existing_masteries: Optional[Dict[str, float]] = None,
        focus_mode: str = "standard",
    ) -> List[Dict[str, Any]]:
        """
        Dynamically adapts a canonical roadmap into a tailored hierarchical curriculum:
        - Filters out niche or overwhelming topics for beginners or learners with tight deadlines.
        - Unlocks foundational topics for intermediate/advanced learners.
        - Auto-credits verified competencies when learner twin mastery >= 0.75.
        - Groups surviving milestones into structured phases/sections.
        """
        existing_masteries = existing_masteries or {}
        current_knowledge = [k.lower().strip() for k in (current_knowledge or []) if k]
        level_norm = target_level.strip().lower()

        # Capacity calculation: hours available
        total_capacity_hours = round((deadline_days * daily_minutes) / 60.0, 1)
        is_constrained = total_capacity_hours < 40 or focus_mode == "fast_track"

        sorted_cnodes = sorted(roadmap.nodes, key=lambda n: n.order)
        selected_nodes = []

        for cnode in sorted_cnodes:
            imp = getattr(cnode, "importance", "essential")
            diff = getattr(cnode, "difficulty", "intermediate")

            # Filtering rules:
            # 1. Niche topics are strictly for advanced/expert or comprehensive focus
            if imp == "niche" and (level_norm in ["beginner", "novice", "entry"] or is_constrained):
                continue

            # 2. Advanced + Expert topics skipped for beginners on constrained schedules
            if is_constrained and imp == "advanced" and diff in ["advanced", "expert"]:
                continue

            selected_nodes.append(cnode)

        if not selected_nodes:
            selected_nodes = sorted_cnodes

        # Group into sections by phase
        phase_map: Dict[str, List[Dict[str, Any]]] = {}
        for cnode in selected_nodes:
            phase_title = cnode.phase or "Core Curriculum"
            if phase_title not in phase_map:
                phase_map[phase_title] = []

            # Determine initial status
            prior_mastery = existing_masteries.get(cnode.concept_id, 0.0)
            is_mastered = prior_mastery >= 0.75

            # Match with declared current_knowledge
            is_declared_known = any(k in cnode.title.lower() or k in (cnode.subtitle or "").lower() for k in current_knowledge)

            if is_mastered:
                status = "completed"
            elif is_declared_known and level_norm in ["intermediate", "advanced", "expert"]:
                status = "unlocked"
            elif level_norm in ["intermediate", "advanced", "expert"] and cnode.tier == "foundation":
                status = "unlocked"
            else:
                status = "not_started"

            phase_map[phase_title].append({
                "concept_id": cnode.concept_id,
                "title": cnode.title,
                "description": cnode.subtitle or cnode.title,
                "difficulty": getattr(cnode, "difficulty", "intermediate"),
                "importance": getattr(cnode, "importance", "essential"),
                "estimated_minutes": cnode.estimated_minutes,
                "prerequisites": cnode.prerequisites or [],
                "learning_objectives": cnode.learning_objectives or [f"Master {cnode.title}"],
                "feynman_prompts": cnode.feynman_prompts or [],
                "key_misconceptions": cnode.key_misconceptions or [],
                "status": status,
            })

        sections = []
        for s_idx, (phase_name, topics) in enumerate(phase_map.items()):
            sections.append({
                "title": phase_name,
                "description": f"Phase {s_idx + 1}: {phase_name} for {roadmap.title}",
                "order_index": s_idx + 1,
                "topics": topics,
            })

        return sections


canonical_roadmap_service = CanonicalRoadmapService()
