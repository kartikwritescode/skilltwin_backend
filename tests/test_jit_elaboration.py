import uuid
import time
import pytest
from sqlalchemy import select
from app.core.database import get_session_factory, init_db
from app.core.db_models import (
    ProfileModel,
    GoalModel,
    AdaptiveLearningPathModel,
    PathNodeModel,
    ElaboratedTopicCacheModel,
)
from app.services.jit_elaboration_service import (
    jit_elaboration_service,
    JITElaborationService,
)


@pytest.mark.asyncio
async def test_jit_elaboration_cache_miss_then_hit():
    """Verify JIT elaboration generates on cache miss, caches globally, and hits on second call at 0 tokens."""
    await init_db()
    session_factory = get_session_factory()

    user_id = str(uuid.uuid4())
    goal_id = str(uuid.uuid4())
    path_id = str(uuid.uuid4())
    concept_id = f"concept_jit_test_{uuid.uuid4().hex[:6]}"
    node_id_1 = f"node_{uuid.uuid4().hex[:8]}"
    node_id_2 = f"node_{uuid.uuid4().hex[:8]}"

    async with session_factory() as session:
        # Create base test records
        profile = ProfileModel(id=user_id, display_name="JIT Learner")
        goal = GoalModel(id=goal_id, user_id=user_id, title="Master JIT Expansion")
        path = AdaptiveLearningPathModel(
            id=path_id, user_id=user_id, goal_id=goal_id, title="JIT Path"
        )
        node1 = PathNodeModel(
            id=node_id_1,
            path_id=path_id,
            concept_id=concept_id,
            title="Async Event Loop Internals",
            order_index=1,
            is_elaborated=False,
        )
        session.add_all([profile, goal, path, node1])
        await session.commit()

    # Call 1: Cache Miss -> LLM Generation
    async with session_factory() as session:
        node_to_elaborate = await session.get(PathNodeModel, node_id_1)
        assert node_to_elaborate.is_elaborated is False

        content = await jit_elaboration_service.elaborate_node_content(node_to_elaborate, session)
        assert content is not None
        assert content["concept_id"] == concept_id
        assert len(content["key_invariants"]) == 3
        assert len(content["practice_questions"]) >= 2
        assert len(content["code_challenges"]) >= 1

        # Verify node is marked elaborated
        refreshed = await session.get(PathNodeModel, node_id_1)
        assert refreshed.is_elaborated is True
        assert refreshed.node_metadata.get("content") is not None

        # Verify global cache table has the record
        cache_entry = await session.get(ElaboratedTopicCacheModel, concept_id)
        assert cache_entry is not None
        assert cache_entry.explanation_markdown is not None

    # Call 2 (Another user or path querying the same concept): Cache HIT -> 0 Tokens
    user_id_2 = str(uuid.uuid4())
    goal_id_2 = str(uuid.uuid4())
    path_id_2 = str(uuid.uuid4())

    async with session_factory() as session:
        profile2 = ProfileModel(id=user_id_2, display_name="JIT Learner 2")
        goal2 = GoalModel(id=goal_id_2, user_id=user_id_2, title="User 2 Goal")
        path2 = AdaptiveLearningPathModel(
            id=path_id_2, user_id=user_id_2, goal_id=goal_id_2, title="JIT Path 2"
        )
        node2 = PathNodeModel(
            id=node_id_2,
            path_id=path_id_2,
            concept_id=concept_id,
            title="Async Event Loop Internals (User 2)",
            order_index=1,
            is_elaborated=False,
        )
        session.add_all([profile2, goal2, path2, node2])
        await session.commit()

        start_time = time.perf_counter()
        cached_content = await jit_elaboration_service.elaborate_node_content(node2, session)
        hit_duration_ms = (time.perf_counter() - start_time) * 1000

        assert cached_content["concept_id"] == concept_id
        assert hit_duration_ms < 20.0, f"Expected cache hit in < 20ms, took {hit_duration_ms:.2f}ms"
        assert node2.is_elaborated is True


@pytest.mark.asyncio
async def test_horizon_window_lazy_expansion():
    """Verify check_and_elaborate_horizon expands only nodes within [N+1, N+H]."""
    session_factory = get_session_factory()

    user_id = str(uuid.uuid4())
    goal_id = str(uuid.uuid4())
    path_id = str(uuid.uuid4())

    async with session_factory() as session:
        profile = ProfileModel(id=user_id, display_name="Horizon Learner")
        goal = GoalModel(id=goal_id, user_id=user_id, title="Horizon Goal")
        path = AdaptiveLearningPathModel(
            id=path_id, user_id=user_id, goal_id=goal_id, title="Horizon Path"
        )
        session.add_all([profile, goal, path])

        # Create 5 sequential nodes: 0, 1, 2, 3, 4
        nodes = []
        for i in range(5):
            node = PathNodeModel(
                id=f"node_h_{uuid.uuid4().hex[:8]}",
                path_id=path_id,
                concept_id=f"concept_h_{i}_{uuid.uuid4().hex[:6]}",
                title=f"Milestone {i}",
                order_index=i,
                is_elaborated=False,
            )
            nodes.append(node)
        session.add_all(nodes)
        await session.commit()

    # Expand horizon window for current_node_order = 0, horizon = 2 -> Should elaborate nodes 1 and 2
    async with session_factory() as session:
        elaborated = await jit_elaboration_service.check_and_elaborate_horizon(
            path_id=path_id, current_node_order=0, horizon=2, session=session
        )
        assert len(elaborated) == 2
        orders = [n.order_index for n in elaborated]
        assert orders == [1, 2]

        # Verify that nodes 3 and 4 remain UN-ELABORATED (lazy deferred)
        all_nodes_res = await session.execute(
            select(PathNodeModel).where(PathNodeModel.path_id == path_id).order_by(PathNodeModel.order_index)
        )
        all_nodes = all_nodes_res.scalars().all()
        assert all_nodes[0].is_elaborated is False  # current completed node
        assert all_nodes[1].is_elaborated is True   # horizon 1
        assert all_nodes[2].is_elaborated is True   # horizon 2
        assert all_nodes[3].is_elaborated is False  # beyond horizon (0 tokens wasted!)
        assert all_nodes[4].is_elaborated is False  # beyond horizon (0 tokens wasted!)
