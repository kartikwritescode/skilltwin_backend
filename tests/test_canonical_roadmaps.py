import pytest
from httpx import AsyncClient
from app.services.canonical_roadmap_service import canonical_roadmap_service
from app.services.journey_service import JourneyService
from app.domain.goals.models import Goal
from app.domain.journeys.models import NodeState


@pytest.mark.asyncio
async def test_canonical_fixtures_loading():
    """Verify that all canonical roadmap fixtures load properly."""
    await canonical_roadmap_service.ensure_fixtures_loaded()
    roadmaps = await canonical_roadmap_service.canonical_repo.list_all()

    assert len(roadmaps) >= 30
    slugs = {r.slug for r in roadmaps}
    assert "flutter_mobile" in slugs
    assert "python_backend" in slugs
    assert "fullstack_web" in slugs
    assert "dsa_problem_solving" in slugs

    flutter_roadmap = await canonical_roadmap_service.canonical_repo.get_by_slug("flutter")
    assert flutter_roadmap is not None
    assert flutter_roadmap.total_nodes >= 16
    assert len(flutter_roadmap.nodes) >= 16
    assert len(flutter_roadmap.embedding) > 0


@pytest.mark.asyncio
async def test_canonical_similarity_search():
    """Verify vector similarity matching finds the right canonical roadmap."""
    await canonical_roadmap_service.ensure_fixtures_loaded()

    # Query matching flutter
    match = await canonical_roadmap_service.find_matching_roadmap(
        goal_title="Flutter & Dart Mobile Architecture",
        goal_description="Cross-platform apps with Riverpod",
        threshold=0.5,
    )
    assert match is not None
    matched_roadmap, score = match
    assert "flutter" in matched_roadmap.slug
    assert score >= 0.5

    # Completely unrelated query
    niche_match = await canonical_roadmap_service.find_matching_roadmap(
        goal_title="Underwater Submarine Acoustic Hydrodynamics",
        threshold=0.99,
    )
    assert niche_match is None


@pytest.mark.asyncio
async def test_deterministic_tailoring_beginner():
    """Verify that beginner learners start at node 1 as CURRENT, rest LOCKED."""
    await canonical_roadmap_service.ensure_fixtures_loaded()
    flutter = await canonical_roadmap_service.canonical_repo.get_by_slug("flutter")

    nodes = canonical_roadmap_service.tailor_roadmap_to_nodes(
        roadmap=flutter,
        journey_id="jrn_test_1",
        current_level="Beginner",
        daily_minutes=30,
    )

    assert len(nodes) >= 14
    assert nodes[0].state == NodeState.CURRENT
    assert nodes[0].progress == 0
    assert nodes[1].state == NodeState.LOCKED
    # Winding positions check
    assert nodes[0].position_y == 0.0
    assert nodes[1].position_y == 140.0


@pytest.mark.asyncio
async def test_deterministic_tailoring_intermediate():
    """Verify that intermediate learners have foundation nodes unlocked (AVAILABLE) without prerequisite blocks."""
    await canonical_roadmap_service.ensure_fixtures_loaded()
    flutter = await canonical_roadmap_service.canonical_repo.get_by_slug("flutter")

    nodes = canonical_roadmap_service.tailor_roadmap_to_nodes(
        roadmap=flutter,
        journey_id="jrn_test_2",
        current_level="Intermediate",
        daily_minutes=30,
    )

    # Node 0 is CURRENT (starting frontier)
    assert nodes[0].state == NodeState.CURRENT
    # Subsequent foundation nodes (nodes 1 and 2) are AVAILABLE (unlocked for skipping/jumping)
    assert nodes[1].state == NodeState.AVAILABLE
    assert nodes[2].state == NodeState.AVAILABLE


@pytest.mark.asyncio
async def test_deterministic_tailoring_twin_mastery():
    """Verify that nodes with prior learner twin mastery (>= 0.75) are auto-credited."""
    await canonical_roadmap_service.ensure_fixtures_loaded()
    flutter = await canonical_roadmap_service.canonical_repo.get_by_slug("flutter")

    prior_masteries = {
        "concept_flutter_mobile_widget_tree_element": 0.85,
    }

    nodes = canonical_roadmap_service.tailor_roadmap_to_nodes(
        roadmap=flutter,
        journey_id="jrn_test_3",
        current_level="Beginner",
        daily_minutes=30,
        existing_masteries=prior_masteries,
    )

    widget_tree_node = next((n for n in nodes if n.concept_id == "concept_flutter_mobile_widget_tree_element"), None)
    if widget_tree_node:
        assert widget_tree_node.state == NodeState.COMPLETED
        assert widget_tree_node.progress == 100


@pytest.mark.asyncio
async def test_tailor_curriculum_for_goal_beginner_filtering():
    """Verify goal-aware curriculum tailoring filters niche topics for beginners."""
    await canonical_roadmap_service.ensure_fixtures_loaded()
    fe = await canonical_roadmap_service.canonical_repo.get_by_slug("frontend")

    # Beginner with 15 mins/day and 30 day deadline (highly constrained)
    beginner_sections = canonical_roadmap_service.tailor_curriculum_for_goal(
        roadmap=fe,
        target_level="Beginner",
        daily_minutes=15,
        deadline_days=30,
        focus_mode="fast_track",
    )

    assert len(beginner_sections) > 0
    beginner_topic_count = sum(len(s["topics"]) for s in beginner_sections)

    # Advanced learner with 60 mins/day
    advanced_sections = canonical_roadmap_service.tailor_curriculum_for_goal(
        roadmap=fe,
        target_level="Advanced",
        daily_minutes=60,
        deadline_days=90,
    )
    advanced_topic_count = sum(len(s["topics"]) for s in advanced_sections)

    # Beginner fast-track should have fewer/focused milestones than comprehensive advanced
    assert beginner_topic_count <= advanced_topic_count
    # All beginner topics should be essential or recommended
    for sec in beginner_sections:
        for top in sec["topics"]:
            assert top["importance"] in ["essential", "recommended"]


@pytest.mark.asyncio
async def test_api_list_and_get_canonical_roadmaps(async_client: AsyncClient):
    """Test REST API endpoints for canonical roadmaps."""
    # 1. List
    res = await async_client.get("/api/v1/roadmaps/canonical")
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 30

    # 2. Get Detail (using slug alias)
    res = await async_client.get("/api/v1/roadmaps/canonical/flutter")
    assert res.status_code == 200
    detail = res.json()
    assert "flutter" in detail["slug"]
    assert len(detail["nodes"]) >= 16
    assert detail["nodes"][0]["feynman_prompts"] is not None

    # 3. Match
    match_payload = {
        "goal_title": "Flutter & Dart Mobile Architecture",
        "threshold": 0.5,
    }
    match_res = await async_client.post("/api/v1/roadmaps/canonical/match", json=match_payload)
    assert match_res.status_code == 200
    match_data = match_res.json()
    assert match_data["matched"] is True
    assert "flutter" in match_data["roadmap"]["slug"]
