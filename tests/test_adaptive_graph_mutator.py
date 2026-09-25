import uuid
import pytest
from sqlalchemy import select
from app.core.database import get_session_factory, init_db
from app.core.db_models import (
    ProfileModel,
    GoalModel,
    AdaptiveLearningPathModel,
    PathNodeModel,
    PathNodeEdgeModel,
)
from app.services.adaptive_graph_mutator import adaptive_graph_mutator
from app.services.adag_assembler import adag_assembler


@pytest.mark.asyncio
async def test_remediation_splice_on_quiz_failure():
    """Verify failing a quiz injects an amber detour remediation bridge and maintains DAG acyclicity."""
    await init_db()
    session_factory = get_session_factory()

    user_id = str(uuid.uuid4())
    goal_id = str(uuid.uuid4())
    path_id = str(uuid.uuid4())
    node_id_1 = f"node_{uuid.uuid4().hex[:8]}"
    node_id_2 = f"node_{uuid.uuid4().hex[:8]}"

    async with session_factory() as session:
        profile = ProfileModel(id=user_id, display_name="Remediation Learner")
        goal = GoalModel(id=goal_id, user_id=user_id, title="Test Path Goal")
        path = AdaptiveLearningPathModel(id=path_id, user_id=user_id, goal_id=goal_id, title="Test Path")

        node1 = PathNodeModel(
            id=node_id_1,
            path_id=path_id,
            concept_id="concept_react_use_effect",
            title="React useEffect & Cleanup",
            state="CURRENT",
            order_index=0,
            node_metadata={"estimated_minutes": 30},
        )
        node2 = PathNodeModel(
            id=node_id_2,
            path_id=path_id,
            concept_id="concept_react_custom_hooks",
            title="React Custom Hooks",
            state="LOCKED",
            order_index=1,
            node_metadata={"estimated_minutes": 45},
        )
        edge = PathNodeEdgeModel(
            id=f"edge_{uuid.uuid4().hex[:8]}",
            path_id=path_id,
            source_node_id=node_id_1,
            target_node_id=node_id_2,
            edge_type="prerequisite",
        )
        session.add_all([profile, goal, path, node1, node2, edge])
        await session.commit()

    # Learner fails quiz (score = 0.40)
    async with session_factory() as session:
        result = await adaptive_graph_mutator.handle_evidence_event(
            path_id=path_id,
            node_id=node_id_1,
            score=0.40,
            confidence=0.50,
            duration_seconds=300,
            misconceptions=["closures_in_listeners"],
            session=session,
        )

        assert result["action"] == "REMEDIATION_SPLICED"
        remediation_node_id = result["remediation_node_id"]
        assert remediation_node_id is not None

        # Verify remediation node in DB
        rem_node = await session.get(PathNodeModel, remediation_node_id)
        assert rem_node is not None
        assert rem_node.is_remediation is True
        assert rem_node.state == "CURRENT"
        assert rem_node.spliced_after_node_id == node_id_1

        # Verify failed node state is REMEDIATING
        failed_node = await session.get(PathNodeModel, node_id_1)
        assert failed_node.state == "REMEDIATING"

        # Verify edge rewiring
        detour_edges = (await session.execute(
            select(PathNodeEdgeModel).where(PathNodeEdgeModel.path_id == path_id)
        )).scalars().all()

        detour_pairs = [(e.source_node_id, e.target_node_id) for e in detour_edges]
        assert (node_id_1, remediation_node_id) in detour_pairs
        assert (remediation_node_id, node_id_2) in detour_pairs

        # Verify entire mutated graph passes acyclicity check
        all_nodes = (await session.execute(
            select(PathNodeModel).where(PathNodeModel.path_id == path_id)
        )).scalars().all()
        sorted_order = adag_assembler.verify_and_sort_dag(
            [{"id": n.id} for n in all_nodes], detour_pairs
        )
        assert len(sorted_order) == 3
        assert sorted_order[0] == node_id_1
        assert sorted_order[1] == remediation_node_id
        assert sorted_order[2] == node_id_2


@pytest.mark.asyncio
async def test_fast_track_mastery_bypass():
    """Verify exceptional score, speed, and confidence transitions downstream introductory topics to BYPASSED."""
    session_factory = get_session_factory()

    user_id = str(uuid.uuid4())
    goal_id = str(uuid.uuid4())
    path_id = str(uuid.uuid4())
    node_id_1 = f"node_{uuid.uuid4().hex[:8]}"
    node_id_2 = f"node_{uuid.uuid4().hex[:8]}"
    node_id_3 = f"node_{uuid.uuid4().hex[:8]}"

    async with session_factory() as session:
        profile = ProfileModel(id=user_id, display_name="FastTrack Learner")
        goal = GoalModel(id=goal_id, user_id=user_id, title="FastTrack Goal")
        path = AdaptiveLearningPathModel(id=path_id, user_id=user_id, goal_id=goal_id, title="FastTrack Path")

        node1 = PathNodeModel(
            id=node_id_1,
            path_id=path_id,
            concept_id="concept_sql_joins",
            title="SQL Complex Joins",
            state="CURRENT",
            order_index=0,
            node_metadata={"estimated_minutes": 30, "tier": "core"},
        )
        # Redundant beginner node downstream
        node2 = PathNodeModel(
            id=node_id_2,
            path_id=path_id,
            concept_id="concept_sql_basic_select",
            title="SQL Basic SELECT & Filtering",
            state="LOCKED",
            order_index=1,
            node_metadata={"estimated_minutes": 20, "tier": "foundational"},
        )
        # Advanced challenge downstream
        node3 = PathNodeModel(
            id=node_id_3,
            path_id=path_id,
            concept_id="concept_sql_indexing",
            title="B-Tree Indexing Optimization",
            state="LOCKED",
            order_index=2,
            node_metadata={"estimated_minutes": 45, "tier": "advanced"},
        )

        edge1 = PathNodeEdgeModel(
            id=f"e_{uuid.uuid4().hex[:8]}", path_id=path_id, source_node_id=node_id_1, target_node_id=node_id_2
        )
        edge2 = PathNodeEdgeModel(
            id=f"e_{uuid.uuid4().hex[:8]}", path_id=path_id, source_node_id=node_id_2, target_node_id=node_id_3
        )
        session.add_all([profile, goal, path, node1, node2, node3, edge1, edge2])
        await session.commit()

    # Fast-track trigger: score=0.96, confidence=0.92, duration=25s (far below 30min * 0.40)
    async with session_factory() as session:
        result = await adaptive_graph_mutator.handle_evidence_event(
            path_id=path_id,
            node_id=node_id_1,
            score=0.96,
            confidence=0.92,
            duration_seconds=25,
            session=session,
        )

        assert result["action"] == "FAST_TRACK_BYPASS"
        assert node_id_2 in result["bypassed_node_ids"]

        # Check DB states
        n1 = await session.get(PathNodeModel, node_id_1)
        n2 = await session.get(PathNodeModel, node_id_2)
        n3 = await session.get(PathNodeModel, node_id_3)

        assert n1.state == "COMPLETED"
        assert n2.state == "BYPASSED"
        assert n3.state == "AVAILABLE"  # Unlocked past the bypassed topic!


@pytest.mark.asyncio
async def test_standard_progression_unlocks_next():
    """Verify standard completion marks node COMPLETED and unlocks downstream AVAILABLE nodes."""
    session_factory = get_session_factory()

    user_id = str(uuid.uuid4())
    goal_id = str(uuid.uuid4())
    path_id = str(uuid.uuid4())
    node_id_1 = f"node_{uuid.uuid4().hex[:8]}"
    node_id_2 = f"node_{uuid.uuid4().hex[:8]}"

    async with session_factory() as session:
        profile = ProfileModel(id=user_id, display_name="Standard Learner")
        goal = GoalModel(id=goal_id, user_id=user_id, title="Standard Goal")
        path = AdaptiveLearningPathModel(id=path_id, user_id=user_id, goal_id=goal_id, title="Standard Path")

        node1 = PathNodeModel(
            id=node_id_1, path_id=path_id, concept_id="concept_standard_1", title="Topic 1",
            state="CURRENT", order_index=0, node_metadata={"estimated_minutes": 25},
        )
        node2 = PathNodeModel(
            id=node_id_2, path_id=path_id, concept_id="concept_standard_2", title="Topic 2",
            state="LOCKED", order_index=1, node_metadata={"estimated_minutes": 30},
        )
        edge = PathNodeEdgeModel(
            id=f"e_{uuid.uuid4().hex[:8]}", path_id=path_id, source_node_id=node_id_1, target_node_id=node_id_2
        )
        session.add_all([profile, goal, path, node1, node2, edge])
        await session.commit()

    async with session_factory() as session:
        result = await adaptive_graph_mutator.handle_evidence_event(
            path_id=path_id,
            node_id=node_id_1,
            score=0.82,
            confidence=0.75,
            duration_seconds=1200,
            session=session,
        )

        assert result["action"] == "STANDARD_PROGRESSION"

        n1 = await session.get(PathNodeModel, node_id_1)
        n2 = await session.get(PathNodeModel, node_id_2)

        assert n1.state == "COMPLETED"
        assert n2.state == "AVAILABLE"
