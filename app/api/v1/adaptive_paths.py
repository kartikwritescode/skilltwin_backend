import uuid
from datetime import date
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import get_db_session
from app.core.security import CurrentUser, get_current_user
from app.core.db_models import (
    GoalModel,
    AdaptiveLearningPathModel,
    PathNodeModel,
    PathNodeEdgeModel,
    MicroSubgraphModel,
)
from app.schemas.adaptive_path import (
    AdaptiveLearningPathRead,
    AdaptivePathGenerateRequest,
    EvidenceSubmissionRequest,
    PacingStatusResponse,
)
from app.services.canonical_registry_service import canonical_registry_service
from app.services.adag_assembler import adag_assembler
from app.services.cpm_pacing_service import cpm_pacing_service
from app.services.jit_elaboration_service import jit_elaboration_service
from app.services.adaptive_graph_mutator import adaptive_graph_mutator
from app.services.pacing_recalibration_service import pacing_recalibration_service
from app.core.logging import logger

router = APIRouter(prefix="/adaptive-paths", tags=["Adaptive Paths"])


@router.post(
    "/generate",
    response_model=AdaptiveLearningPathRead,
    status_code=status.HTTP_201_CREATED,
    summary="Generate 0-Token ADAG Adaptive Path",
)
async def generate_adaptive_path(
    request: AdaptivePathGenerateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Coordinates CanonicalRegistryService, TopologicalAssembler, and CPMPacingService
    to assemble and prune a validated DAG for the user goal at 0 LLM tokens in <200ms.
    """
    # 1. Fetch user goal
    goal = await session.get(GoalModel, request.goal_id)
    if not goal or str(goal.user_id) != str(current_user.user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Goal '{request.goal_id}' not found for authenticated user",
        )

    target_deadline = request.target_deadline or goal.deadline
    daily_budget = request.daily_budget_minutes or goal.daily_minutes or 30

    # 2. Retrieve micro-subgraphs from Canonical Knowledge Registry
    subgraphs = await canonical_registry_service.search_subgraphs_semantic(
        query=goal.title,
        limit=10,
        fallback_to_synthesis=True,
        session=session,
    )

    if not subgraphs:
        await canonical_registry_service.seed_canonical_subgraphs_if_empty(session)
        subgraphs = await canonical_registry_service.search_subgraphs_semantic(
            query=goal.title,
            limit=10,
            fallback_to_synthesis=True,
            session=session,
        )

    if not subgraphs:
        # Fallback to query available subgraphs in DB
        stmt = select(MicroSubgraphModel).limit(8)
        subgraphs = list((await session.execute(stmt)).scalars().all())

    # 3. Topological Assembly (Kahn's Algorithm & Transitive Reduction)
    topological_nodes, reduced_edges = adag_assembler.stitch_subgraphs(subgraphs)

    # 4. Critical Path Method (CPM) Pacing & Capacity Pruning
    if target_deadline:
        days_until_deadline = (target_deadline - date.today()).days
        if days_until_deadline > 0:
            prune_result = cpm_pacing_service.prune_to_capacity(
                nodes=topological_nodes,
                edges=reduced_edges,
                target_deadline_days=days_until_deadline,
                daily_budget_minutes=daily_budget,
            )
            topological_nodes = prune_result["pruned_nodes"]
            reduced_edges = prune_result["pruned_edges"]

    # 5. Persist AdaptiveLearningPathModel, PathNodeModel, and PathNodeEdgeModel
    path_id = str(uuid.uuid4())
    new_path = AdaptiveLearningPathModel(
        id=path_id,
        user_id=str(current_user.user_id),
        goal_id=str(goal.id),
        title=goal.title,
        status="ACTIVE",
        target_deadline=target_deadline,
        daily_budget_minutes=daily_budget,
        velocity_factor=1.0,
        path_metadata={"initial_subgraph_count": len(subgraphs)},
    )
    session.add(new_path)
    await session.flush()

    node_id_map: Dict[str, str] = {}
    persisted_nodes: List[PathNodeModel] = []
    for n in topological_nodes:
        db_node_id = f"node_{uuid.uuid4().hex[:16]}"
        node_id_map[n["id"]] = db_node_id

        initial_state = n.get("state", "LOCKED")
        if n.get("order_index") == 0:
            initial_state = "CURRENT"

        node_model = PathNodeModel(
            id=db_node_id,
            path_id=path_id,
            subgraph_id=n.get("subgraph_id"),
            concept_id=n.get("concept_id") or f"concept_{n['id']}",
            title=n.get("title", ""),
            state=initial_state,
            order_index=n.get("order_index", 0),
            is_remediation=False,
            spliced_after_node_id=None,
            is_elaborated=False,
            mastery_score=0.0,
            time_spent_minutes=0,
            node_metadata={
                "tier": n.get("tier", "core"),
                "estimated_minutes": n.get("estimated_minutes", 30),
                "subgraph_slug": n.get("subgraph_slug", ""),
            },
        )
        session.add(node_model)
        persisted_nodes.append(node_model)

    persisted_edges: List[PathNodeEdgeModel] = []
    for src, dst in reduced_edges:
        if src in node_id_map and dst in node_id_map:
            edge_model = PathNodeEdgeModel(
                id=f"edge_{uuid.uuid4().hex[:16]}",
                path_id=path_id,
                source_node_id=node_id_map[src],
                target_node_id=node_id_map[dst],
                edge_type="prerequisite",
            )
            session.add(edge_model)
            persisted_edges.append(edge_model)

    await session.commit()

    stmt = (
        select(AdaptiveLearningPathModel)
        .options(
            selectinload(AdaptiveLearningPathModel.nodes),
            selectinload(AdaptiveLearningPathModel.edges),
        )
        .where(AdaptiveLearningPathModel.id == path_id)
    )
    result = await session.execute(stmt)
    persisted_path = result.scalar_one()
    persisted_path.nodes.sort(key=lambda x: x.order_index)

    logger.info(
        f"[AdaptivePathsAPI] Successfully generated ADAG path '{path_id}' with "
        f"{len(persisted_path.nodes)} nodes and {len(persisted_path.edges)} edges."
    )
    return persisted_path


@router.get(
    "/{path_id}",
    response_model=AdaptiveLearningPathRead,
    summary="Get Adaptive Path Graph with Nodes, Edges, and Velocity",
)
async def get_adaptive_path(
    path_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Returns path metadata, all nodes sorted by order_index, edges, and velocity metrics.
    """
    stmt = (
        select(AdaptiveLearningPathModel)
        .options(
            selectinload(AdaptiveLearningPathModel.nodes),
            selectinload(AdaptiveLearningPathModel.edges),
        )
        .where(AdaptiveLearningPathModel.id == path_id)
    )
    result = await session.execute(stmt)
    path = result.scalar_one_or_none()

    if not path or str(path.user_id) != str(current_user.user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Adaptive path '{path_id}' not found",
        )

    path.nodes.sort(key=lambda n: n.order_index)

    velocity_metrics = await pacing_recalibration_service.calculate_rolling_velocity(
        user_id=str(current_user.user_id),
        path_id=path_id,
        session=session,
    )
    path.velocity_metrics = velocity_metrics
    return path


@router.post(
    "/{path_id}/nodes/{node_id}/expand",
    summary="JIT Elaborate Node Content",
)
async def expand_node_content(
    path_id: str,
    node_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Manually or lazily triggers JITElaborationService.elaborate_node_content.
    """
    node = await session.get(PathNodeModel, node_id)
    if not node or str(node.path_id) != str(path_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Node '{node_id}' not found in path '{path_id}'",
        )

    content = await jit_elaboration_service.elaborate_node_content(node, session=session)
    return {
        "node_id": node.id,
        "concept_id": node.concept_id,
        "is_elaborated": node.is_elaborated,
        "content": content,
    }


@router.post(
    "/{path_id}/nodes/{node_id}/evidence",
    summary="Submit Quiz/Teach Evidence & Mutate Graph",
)
async def submit_node_evidence(
    path_id: str,
    node_id: str,
    evidence: EvidenceSubmissionRequest,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Submits quiz/teach evidence, triggers AdaptiveGraphMutator.handle_evidence_event,
    and returns mutated graph diff.
    """
    node = await session.get(PathNodeModel, node_id)
    if not node or str(node.path_id) != str(path_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Node '{node_id}' not found in path '{path_id}'",
        )

    mutation_result = await adaptive_graph_mutator.handle_evidence_event(
        path_id=path_id,
        node_id=node_id,
        score=evidence.score,
        confidence=evidence.confidence,
        duration_seconds=evidence.duration_seconds,
        misconceptions=evidence.misconceptions,
        session=session,
    )
    return mutation_result


@router.get(
    "/{path_id}/pacing-status",
    response_model=PacingStatusResponse,
    summary="Get Pacing Projection & Active Alerts",
)
async def get_pacing_status(
    path_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """
    Returns PacingRecalibrationService.project_completion_timeline and active pacing alerts.
    """
    path = await session.get(AdaptiveLearningPathModel, path_id)
    if not path or str(path.user_id) != str(current_user.user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Adaptive path '{path_id}' not found",
        )

    timeline = await pacing_recalibration_service.project_completion_timeline(path_id, session=session)
    alert = await pacing_recalibration_service.evaluate_pacing_alerts(path_id, session=session)
    return PacingStatusResponse(timeline=timeline, alert=alert)
