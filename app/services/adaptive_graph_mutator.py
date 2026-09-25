import uuid
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.core.database import get_session_factory
from app.core.db_models import PathNodeModel, PathNodeEdgeModel
from app.services.adag_assembler import adag_assembler, CyclicDependencyError
from app.services.jit_elaboration_service import jit_elaboration_service


class AdaptiveGraphMutator:
    """
    Continuous In-Flight Graph Mutation Loop for SkillTwin ADAG Engine.
    Dynamically splices targeted remediation detour nodes upon quiz failure or misconceptions,
    bypasses redundant downstream introductory material on rapid high-confidence mastery,
    and unlocks topological successors while maintaining strict DAG invariants.
    """

    async def handle_evidence_event(
        self,
        path_id: str,
        node_id: str,
        score: float,
        confidence: float = 0.5,
        duration_seconds: int = 120,
        misconceptions: Optional[List[str]] = None,
        session: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        """
        Processes learner telemetry evidence and dispatches to appropriate graph mutator:
        1. Remediation Trigger: score < 0.50 or critical misconceptions.
        2. Fast-Track Trigger: score >= 0.90, confidence >= 0.85, duration < 0.40 * estimated.
        3. Standard Progression: advances cursor and unlocks next milestone.
        """
        if session is None:
            session_factory = get_session_factory()
            async with session_factory() as sess:
                return await self.handle_evidence_event(
                    path_id, node_id, score, confidence, duration_seconds, misconceptions, sess
                )

        node = await session.get(PathNodeModel, node_id)
        if not node:
            raise ValueError(f"PathNode '{node_id}' not found in path '{path_id}'")

        misconceptions = misconceptions or []

        # Record mastery and time spent
        node.mastery_score = max(node.mastery_score, score)
        node.time_spent_minutes += max(1, round(duration_seconds / 60))

        estimated_seconds = node.node_metadata.get("estimated_minutes", 30) * 60

        # Condition 1: Remediation Trigger
        if score < 0.50 or (len(misconceptions) > 0 and score < 0.70):
            logger.info(
                f"[AdaptiveGraphMutator] Remediation triggered for node '{node.title}' "
                f"(score={score:.2f}, misconceptions={len(misconceptions)})"
            )
            remediation_node = await self.splice_remediation_node(
                path_id=path_id,
                failed_node_id=node_id,
                prerequisite_concept=misconceptions[0] if misconceptions else None,
                session=session,
            )

            if misconceptions:
                await self.inoculate_misconceptions(path_id, node_id, misconceptions, session)

            return {
                "action": "REMEDIATION_SPLICED",
                "path_id": path_id,
                "node_id": node_id,
                "remediation_node_id": remediation_node.id,
                "remediation_node_title": remediation_node.title,
                "score": score,
                "misconceptions": misconceptions,
                "message": f"Remediation bridge '{remediation_node.title}' spliced to resolve prerequisite gap.",
            }

        # Condition 2: Fast-Track Mastery Bypass Trigger
        if score >= 0.90 and confidence >= 0.85 and duration_seconds < (0.40 * estimated_seconds):
            logger.info(
                f"[AdaptiveGraphMutator] Fast-track bypass triggered for node '{node.title}' "
                f"(score={score:.2f}, confidence={confidence:.2f}, speed={duration_seconds}s vs {estimated_seconds}s)"
            )
            bypassed_ids = await self.fast_track_bypass(
                path_id=path_id, mastered_node_id=node_id, session=session
            )

            return {
                "action": "FAST_TRACK_BYPASS",
                "path_id": path_id,
                "node_id": node_id,
                "bypassed_node_ids": bypassed_ids,
                "score": score,
                "confidence": confidence,
                "message": f"Exceptional mastery demonstrated ({int(score * 100)}%). Bypassed {len(bypassed_ids)} redundant downstream topics.",
            }

        # Condition 3: Standard Progression
        node.state = "COMPLETED"
        unlocked_nodes = await self._unlock_downstream_successors(path_id, node_id, session)

        await session.commit()

        # Trigger JIT background expansion for upcoming horizon
        jit_elaboration_service.pre_warm_horizon_worker(path_id, node.order_index, horizon=2)

        return {
            "action": "STANDARD_PROGRESSION",
            "path_id": path_id,
            "node_id": node_id,
            "score": score,
            "unlocked_node_ids": [n.id for n in unlocked_nodes],
            "message": "Milestone mastered. Downstream concepts unlocked.",
        }

    async def splice_remediation_node(
        self,
        path_id: str,
        failed_node_id: str,
        session: AsyncSession,
        prerequisite_concept: Optional[str] = None,
    ) -> PathNodeModel:
        """
        Dynamically inserts a targeted 15-minute diagnostic bridge node between the failed
        node and its downstream milestones, rewiring edges without creating cycles.
        """
        failed_node = await session.get(PathNodeModel, failed_node_id)
        if not failed_node:
            raise ValueError(f"Failed node '{failed_node_id}' does not exist")

        # Avoid duplicate splicing
        stmt = select(PathNodeModel).where(
            PathNodeModel.path_id == path_id,
            PathNodeModel.spliced_after_node_id == failed_node_id,
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing:
            return existing

        remediation_id = f"remediation_{failed_node_id}_{uuid.uuid4().hex[:6]}"
        concept_suffix = prerequisite_concept or failed_node.concept_id
        remediation_concept_id = f"remediation_{concept_suffix}"

        target_order = failed_node.order_index + 1

        # Shift downstream nodes order_index by +1
        await session.execute(
            update(PathNodeModel)
            .where(
                PathNodeModel.path_id == path_id,
                PathNodeModel.order_index >= target_order,
            )
            .values(order_index=PathNodeModel.order_index + 1)
        )

        remediation_node = PathNodeModel(
            id=remediation_id,
            path_id=path_id,
            subgraph_id=failed_node.subgraph_id,
            concept_id=remediation_concept_id,
            title=f"Diagnostic Bridge: Remediation for {failed_node.title}",
            state="CURRENT",
            order_index=target_order,
            is_remediation=True,
            spliced_after_node_id=failed_node_id,
            is_elaborated=False,
            mastery_score=0.0,
            time_spent_minutes=0,
            node_metadata={
                "failed_node_id": failed_node_id,
                "target_concept": concept_suffix,
                "estimated_minutes": 15,
            },
        )
        session.add(remediation_node)
        await session.flush()

        # Query outgoing edges from failed_node to downstream successors
        edge_stmt = select(PathNodeEdgeModel).where(
            PathNodeEdgeModel.path_id == path_id,
            PathNodeEdgeModel.source_node_id == failed_node_id,
        )
        outgoing_edges = list((await session.execute(edge_stmt)).scalars().all())

        # Insert detour edge: failed_node -> remediation_node
        detour_edge_1 = PathNodeEdgeModel(
            id=f"edge_rem_{uuid.uuid4().hex[:8]}",
            path_id=path_id,
            source_node_id=failed_node_id,
            target_node_id=remediation_id,
            edge_type="remediation_detour",
        )
        session.add(detour_edge_1)

        # Connect remediation_node to downstream successors
        for out_edge in outgoing_edges:
            detour_edge_2 = PathNodeEdgeModel(
                id=f"edge_rem_{uuid.uuid4().hex[:8]}",
                path_id=path_id,
                source_node_id=remediation_id,
                target_node_id=out_edge.target_node_id,
                edge_type="remediation_detour",
            )
            session.add(detour_edge_2)

        # Mark failed node as REMEDIATING
        failed_node.state = "REMEDIATING"

        await session.commit()
        await session.refresh(remediation_node)
        logger.info(
            f"[AdaptiveGraphMutator] Spliced remediation node '{remediation_node.id}' "
            f"after '{failed_node_id}'"
        )
        return remediation_node

    async def fast_track_bypass(
        self, path_id: str, mastered_node_id: str, session: AsyncSession
    ) -> List[str]:
        """
        Bypasses downstream introductory/foundational milestones when learner demonstrates
        swift mastery (score >= 90%, confidence >= 85%).
        """
        mastered_node = await session.get(PathNodeModel, mastered_node_id)
        if not mastered_node:
            return []

        mastered_node.state = "COMPLETED"

        # Find immediate downstream successor nodes
        stmt = (
            select(PathNodeModel)
            .join(PathNodeEdgeModel, PathNodeEdgeModel.target_node_id == PathNodeModel.id)
            .where(
                PathNodeEdgeModel.path_id == path_id,
                PathNodeEdgeModel.source_node_id == mastered_node_id,
            )
        )
        successors = list((await session.execute(stmt)).scalars().all())

        bypassed_ids: List[str] = []
        for succ in successors:
            tier = succ.node_metadata.get("tier", "core")
            # If successor is introductory, foundational, or core with low complexity
            if tier in ["foundational", "core"] and succ.state in ["LOCKED", "AVAILABLE"]:
                succ.state = "BYPASSED"
                bypassed_ids.append(succ.id)

        # Unlock subsequent non-bypassed nodes
        for succ in successors:
            if succ.state == "BYPASSED":
                await self._unlock_downstream_successors(path_id, succ.id, session)
            elif succ.state == "LOCKED":
                succ.state = "AVAILABLE"

        await session.commit()
        logger.info(
            f"[AdaptiveGraphMutator] Bypassed {len(bypassed_ids)} downstream topics "
            f"after mastering '{mastered_node_id}'"
        )
        return bypassed_ids

    async def inoculate_misconceptions(
        self,
        path_id: str,
        active_node_id: str,
        misconception_tags: List[str],
        session: AsyncSession,
    ):
        """
        Injects adversarial counter-example diagnostic questions into the active node
        to force cognitive dissonance and eliminate persistent misconceptions.
        """
        node = await session.get(PathNodeModel, active_node_id)
        if not node:
            return

        meta = dict(node.node_metadata or {})
        existing_tags = meta.get("misconceptions", [])
        updated_tags = list(set(existing_tags + misconception_tags))
        meta["misconceptions"] = updated_tags

        # Inject diagnostic counter-examples
        inoculation_questions = meta.get("inoculation_questions", [])
        for tag in misconception_tags:
            inoculation_questions.append({
                "tag": tag,
                "prompt": f"Adversarial Inoculation: Why is the assumption '{tag}' invalid in production systems?",
                "rubric": "Learner must identify the specific invariant violation.",
            })
        meta["inoculation_questions"] = inoculation_questions

        node.node_metadata = meta
        await session.commit()

    async def _unlock_downstream_successors(
        self, path_id: str, completed_node_id: str, session: AsyncSession
    ) -> List[PathNodeModel]:
        """
        Evaluates downstream successors of a completed or bypassed node.
        Unlocks nodes whose prerequisite antecedents are all COMPLETED or BYPASSED.
        """
        edge_stmt = select(PathNodeEdgeModel).where(
            PathNodeEdgeModel.path_id == path_id,
            PathNodeEdgeModel.source_node_id == completed_node_id,
        )
        edges = list((await session.execute(edge_stmt)).scalars().all())

        unlocked: List[PathNodeModel] = []

        for edge in edges:
            succ = await session.get(PathNodeModel, edge.target_node_id)
            if not succ or succ.state in ["COMPLETED", "BYPASSED"]:
                continue

            # Query all incoming edges for succ
            inc_stmt = select(PathNodeModel).join(
                PathNodeEdgeModel, PathNodeEdgeModel.source_node_id == PathNodeModel.id
            ).where(
                PathNodeEdgeModel.path_id == path_id,
                PathNodeEdgeModel.target_node_id == succ.id,
            )
            antecedents = list((await session.execute(inc_stmt)).scalars().all())

            # Check if all antecedents are completed or bypassed
            all_satisfied = all(a.state in ["COMPLETED", "BYPASSED"] for a in antecedents)
            if all_satisfied and succ.state == "LOCKED":
                succ.state = "AVAILABLE"
                unlocked.append(succ)

        return unlocked


adaptive_graph_mutator = AdaptiveGraphMutator()
