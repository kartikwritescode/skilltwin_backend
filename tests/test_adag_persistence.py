import uuid
import pytest
from datetime import datetime, date, timezone
from sqlalchemy import select
from app.core.database import get_session_factory, init_db
from app.core.db_models import (
    ProfileModel,
    GoalModel,
    CanonicalOntologyModel,
    MicroSubgraphModel,
    AdaptiveLearningPathModel,
    PathNodeModel,
    PathNodeEdgeModel,
    ElaboratedTopicCacheModel,
)
from app.schemas.adaptive_path import (
    MicroSubgraphCreate,
    MicroSubgraphRead,
    PathNodeRead,
    PathNodeEdgeRead,
    AdaptiveLearningPathRead,
    ElaboratedTopicContent,
    PracticeQuestion,
    PracticeQuestionOption,
    CodeChallenge,
    CodeChallengeTestCase,
)


@pytest.mark.asyncio
async def test_database_initialization_creates_adag_tables():
    """Verify that init_db() creates all ADAG tables without errors."""
    await init_db()
    session_factory = get_session_factory()
    async with session_factory() as session:
        # Check that we can query all 6 new tables cleanly
        ontologies = await session.execute(select(CanonicalOntologyModel).limit(1))
        assert ontologies is not None

        subgraphs = await session.execute(select(MicroSubgraphModel).limit(1))
        assert subgraphs is not None

        paths = await session.execute(select(AdaptiveLearningPathModel).limit(1))
        assert paths is not None

        nodes = await session.execute(select(PathNodeModel).limit(1))
        assert nodes is not None

        edges = await session.execute(select(PathNodeEdgeModel).limit(1))
        assert edges is not None

        cache = await session.execute(select(ElaboratedTopicCacheModel).limit(1))
        assert cache is not None


@pytest.mark.asyncio
async def test_canonical_ontology_and_micro_subgraph_cascade():
    """Verify CanonicalOntologyModel and MicroSubgraphModel relationship & cascade delete."""
    session_factory = get_session_factory()
    ontology_id = f"test_ont_{uuid.uuid4().hex[:8]}"
    subgraph_id_1 = f"test_sub_{uuid.uuid4().hex[:8]}"
    subgraph_id_2 = f"test_sub_{uuid.uuid4().hex[:8]}"

    async with session_factory() as session:
        ontology = CanonicalOntologyModel(
            id=ontology_id,
            domain="backend_engineering",
            title="Backend Systems Architecture",
            description="Comprehensive backend curriculum",
            total_nodes=2,
        )
        session.add(ontology)
        await session.flush()

        sg1 = MicroSubgraphModel(
            id=subgraph_id_1,
            ontology_id=ontology_id,
            slug=f"slug-{uuid.uuid4().hex[:8]}",
            title="Relational DB Indexing",
            tier="core",
            estimated_minutes=45,
            prerequisites=[],
        )
        sg2 = MicroSubgraphModel(
            id=subgraph_id_2,
            ontology_id=ontology_id,
            slug=f"slug-{uuid.uuid4().hex[:8]}",
            title="B-Tree Index Deep Dive",
            tier="advanced",
            estimated_minutes=60,
            prerequisites=[sg1.slug],
        )
        session.add_all([sg1, sg2])
        await session.commit()

    # Verify retrieval with relationship
    async with session_factory() as session:
        result = await session.execute(
            select(CanonicalOntologyModel).where(CanonicalOntologyModel.id == ontology_id)
        )
        fetched_ont = result.scalar_one_or_none()
        assert fetched_ont is not None
        assert fetched_ont.title == "Backend Systems Architecture"

        sg_result = await session.execute(
            select(MicroSubgraphModel).where(MicroSubgraphModel.ontology_id == ontology_id)
        )
        fetched_sgs = sg_result.scalars().all()
        assert len(fetched_sgs) == 2

    # Verify CASCADE DELETE
    async with session_factory() as session:
        del_ont = await session.get(CanonicalOntologyModel, ontology_id)
        await session.delete(del_ont)
        await session.commit()

    async with session_factory() as session:
        sg_after = await session.execute(
            select(MicroSubgraphModel).where(MicroSubgraphModel.ontology_id == ontology_id)
        )
        assert len(sg_after.scalars().all()) == 0


@pytest.mark.asyncio
async def test_adaptive_learning_path_nodes_and_edges():
    """Verify AdaptiveLearningPathModel, PathNodeModel, and PathNodeEdgeModel with relationships."""
    session_factory = get_session_factory()
    test_user_id = str(uuid.uuid4())
    test_goal_id = str(uuid.uuid4())
    path_id = str(uuid.uuid4())
    node_1_id = f"node_{uuid.uuid4().hex[:8]}"
    node_2_id = f"node_{uuid.uuid4().hex[:8]}"
    edge_id = f"edge_{uuid.uuid4().hex[:8]}"

    async with session_factory() as session:
        # Create user profile and goal first for valid foreign keys
        profile = ProfileModel(id=test_user_id, display_name="Test Learner")
        goal = GoalModel(
            id=test_goal_id,
            user_id=test_user_id,
            title="Become Senior AI Engineer",
            target_level="Advanced",
        )
        session.add_all([profile, goal])
        await session.flush()

        # Create AdaptiveLearningPath
        path = AdaptiveLearningPathModel(
            id=path_id,
            user_id=test_user_id,
            goal_id=test_goal_id,
            title="AI Engineer Path",
            status="ACTIVE",
            target_deadline=date(2026, 12, 31),
            daily_budget_minutes=45,
            velocity_factor=1.2,
            path_metadata={"curriculum_type": "adag"},
        )
        session.add(path)
        await session.flush()

        # Create Nodes
        node_1 = PathNodeModel(
            id=node_1_id,
            path_id=path_id,
            subgraph_id="sub_python_async",
            concept_id="python_asyncio_event_loop",
            title="Python AsyncIO Event Loop",
            state="COMPLETED",
            order_index=0,
            is_remediation=False,
            is_elaborated=True,
            mastery_score=0.92,
            time_spent_minutes=40,
            node_metadata={"key_takeaway": "Non-blocking concurrency"},
        )
        node_2 = PathNodeModel(
            id=node_2_id,
            path_id=path_id,
            subgraph_id="sub_python_async",
            concept_id="python_task_groups",
            title="Python 3.11+ TaskGroups",
            state="CURRENT",
            order_index=1,
            is_remediation=False,
            is_elaborated=False,
            mastery_score=0.0,
            time_spent_minutes=0,
            node_metadata={},
        )
        session.add_all([node_1, node_2])
        await session.flush()

        # Create Edge
        edge = PathNodeEdgeModel(
            id=edge_id,
            path_id=path_id,
            source_node_id=node_1_id,
            target_node_id=node_2_id,
            edge_type="prerequisite",
        )
        session.add(edge)
        await session.commit()

    # Query and test relations
    async with session_factory() as session:
        fetched_path = await session.get(AdaptiveLearningPathModel, path_id)
        assert fetched_path is not None
        assert fetched_path.title == "AI Engineer Path"
        assert fetched_path.velocity_factor == 1.2

        # Check nodes
        nodes_res = await session.execute(
            select(PathNodeModel).where(PathNodeModel.path_id == path_id).order_by(PathNodeModel.order_index)
        )
        nodes = nodes_res.scalars().all()
        assert len(nodes) == 2
        assert nodes[0].id == node_1_id
        assert nodes[0].mastery_score == 0.92
        assert nodes[1].id == node_2_id

        # Check edges
        edges_res = await session.execute(
            select(PathNodeEdgeModel).where(PathNodeEdgeModel.path_id == path_id)
        )
        edges = edges_res.scalars().all()
        assert len(edges) == 1
        assert edges[0].source_node_id == node_1_id
        assert edges[0].target_node_id == node_2_id

    # Test CASCADE delete on AdaptiveLearningPath
    async with session_factory() as session:
        path_to_del = await session.get(AdaptiveLearningPathModel, path_id)
        await session.delete(path_to_del)
        await session.commit()

    async with session_factory() as session:
        remaining_nodes = await session.execute(
            select(PathNodeModel).where(PathNodeModel.path_id == path_id)
        )
        assert len(remaining_nodes.scalars().all()) == 0

        remaining_edges = await session.execute(
            select(PathNodeEdgeModel).where(PathNodeEdgeModel.path_id == path_id)
        )
        assert len(remaining_edges.scalars().all()) == 0


@pytest.mark.asyncio
async def test_elaborated_topic_cache_and_pydantic_schemas():
    """Verify ElaboratedTopicCacheModel persistence and ElaboratedTopicContent validation."""
    session_factory = get_session_factory()
    concept_id = f"concept_{uuid.uuid4().hex[:8]}"

    # Validate with Pydantic first
    topic_content = ElaboratedTopicContent(
        concept_id=concept_id,
        difficulty="intermediate",
        explanation_markdown="## AsyncIO Fundamentals\n\nThe event loop coordinates coroutines...",
        key_invariants=[
            "Never execute blocking CPU-bound code in the event loop",
            "Always await awaitables or schedule them as tasks",
            "Handle CancelledError gracefully in task cleanup",
        ],
        practice_questions=[
            PracticeQuestion(
                id="q1",
                question="What happens if time.sleep(5) is called in an async def function?",
                options=[
                    PracticeQuestionOption(id="opt_a", text="The whole event loop is blocked", is_correct=True),
                    PracticeQuestionOption(id="opt_b", text="Only that coroutine pauses", is_correct=False),
                ],
                explanation="time.sleep is synchronous and halts the thread.",
            )
        ],
        code_challenges=[
            CodeChallenge(
                id="c1",
                title="Convert Synchronous Fetch to Async",
                instructions="Use httpx.AsyncClient instead of requests.",
                starter_code="def fetch(url): pass",
                solution_code="async def fetch(url): pass",
                test_cases=[
                    CodeChallengeTestCase(
                        input="https://api.example.com",
                        expected_output="status: 200",
                    )
                ],
            )
        ],
    )

    # Persist to ElaboratedTopicCacheModel
    async with session_factory() as session:
        cache_entry = ElaboratedTopicCacheModel(
            concept_id=topic_content.concept_id,
            difficulty=topic_content.difficulty,
            explanation_markdown=topic_content.explanation_markdown,
            key_invariants=topic_content.key_invariants,
            practice_questions=[q.model_dump() for q in topic_content.practice_questions],
            code_challenges=[c.model_dump() for c in topic_content.code_challenges],
            prompt_version=topic_content.prompt_version,
        )
        session.add(cache_entry)
        await session.commit()

    # Retrieve and validate round-trip
    async with session_factory() as session:
        saved_entry = await session.get(ElaboratedTopicCacheModel, concept_id)
        assert saved_entry is not None
        assert saved_entry.difficulty == "intermediate"
        assert len(saved_entry.key_invariants) == 3

        # Validate with Pydantic from_attributes / dict
        validated = ElaboratedTopicContent.model_validate(saved_entry)
        assert validated.concept_id == concept_id
        assert len(validated.practice_questions) == 1
        assert validated.practice_questions[0].options[0].is_correct is True
        assert len(validated.code_challenges) == 1
        assert validated.code_challenges[0].test_cases[0].expected_output == "status: 200"


def test_pydantic_subgraph_and_path_schemas():
    """Verify serialization and validation of MicroSubgraph and Path Pydantic schemas."""
    create_schema = MicroSubgraphCreate(
        slug="react-custom-hooks",
        title="React Custom Hooks & State Encapsulation",
        tier="advanced",
        estimated_minutes=50,
        prerequisites=["react-use-effect", "react-use-state"],
    )
    assert create_schema.slug == "react-custom-hooks"
    assert create_schema.tier == "advanced"

    read_schema = MicroSubgraphRead(
        id="sub_react_hooks",
        slug=create_schema.slug,
        title=create_schema.title,
        tier=create_schema.tier,
        estimated_minutes=create_schema.estimated_minutes,
        prerequisites=create_schema.prerequisites,
        created_at=datetime.now(timezone.utc),
    )
    assert read_schema.id == "sub_react_hooks"
    dumped = read_schema.model_dump()
    assert dumped["tier"] == "advanced"
