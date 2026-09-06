import pytest
from app.domain.journeys.models import Journey, JourneyNode, NodeState, JourneyStatus, GenerationStatus
from app.services.journey_service import JourneyService, journey_service
from app.repositories.journey_repository import JourneyRepository


@pytest.fixture
def standalone_journey_service():
    """Provides an isolated JourneyService instance for engine unit testing."""
    repo = JourneyRepository()
    return JourneyService(journey_repo=repo)


@pytest.fixture
def sample_journey():
    """Builds a deterministic 4-node sequential journey."""
    journey = Journey(
        id="jrn_test_engine",
        goal_id="goal_test_01",
        user_id="user_test_01",
        title="Flutter Mastery",
        progress=0,
        status=JourneyStatus.ACTIVE,
        generation_status=GenerationStatus.READY,
        nodes=[
            JourneyNode(
                id="node_01",
                journey_id="jrn_test_engine",
                concept_id="concept_dart_basics",
                title="Dart Basics",
                subtitle="Syntax and primitive types",
                phase="Foundations",
                order=1,
                state=NodeState.CURRENT,
                progress=50,
                prerequisites=[],
            ),
            JourneyNode(
                id="node_02",
                journey_id="jrn_test_engine",
                concept_id="concept_oop",
                title="OOP in Dart",
                subtitle="Classes and mixins",
                phase="Foundations",
                order=2,
                state=NodeState.LOCKED,
                progress=0,
                prerequisites=["node_01"],
            ),
            JourneyNode(
                id="node_03",
                journey_id="jrn_test_engine",
                concept_id="concept_async",
                title="Async and Streams",
                subtitle="Futures and streams",
                phase="Core",
                order=3,
                state=NodeState.LOCKED,
                progress=0,
                prerequisites=["node_02"],
            ),
            JourneyNode(
                id="node_04",
                journey_id="jrn_test_engine",
                concept_id="concept_state",
                title="State Architecture",
                subtitle="Riverpod and Bloc",
                phase="Advanced",
                order=4,
                state=NodeState.LOCKED,
                progress=0,
                prerequisites=["node_03"],
            ),
        ]
    )
    return journey


# ------------------------------------------------------------------------------
# 1. Journey Progress Calculation
# ------------------------------------------------------------------------------
def test_journey_progress_calculation(standalone_journey_service: JourneyService, sample_journey: Journey):
    # node_01 is 50%, rest are 0% -> (50 + 0 + 0 + 0) / 4 = 12.5 -> 12 (round half to even)
    progress = standalone_journey_service.calculate_progress(sample_journey)
    assert progress in (12, 13)

    # Mark node_01 COMPLETED (contributes 100%) and node_02 progress 50%
    sample_journey.nodes[0].state = NodeState.COMPLETED
    sample_journey.nodes[1].progress = 50
    # (100 + 50 + 0 + 0) / 4 = 37.5 -> 38%
    progress = standalone_journey_service.calculate_progress(sample_journey)
    assert progress == 38

    # Mark all COMPLETED -> 100%
    for n in sample_journey.nodes:
        n.state = NodeState.COMPLETED
    progress = standalone_journey_service.calculate_progress(sample_journey)
    assert progress == 100


# ------------------------------------------------------------------------------
# 2. Current Node Identification
# ------------------------------------------------------------------------------
def test_current_node(sample_journey: Journey):
    current_node = next((n for n in sample_journey.nodes if n.state == NodeState.CURRENT), None)
    assert current_node is not None
    assert current_node.id == "node_01"
    assert current_node.state == NodeState.CURRENT


# ------------------------------------------------------------------------------
# 3. Prerequisite Locked State
# ------------------------------------------------------------------------------
def test_prerequisite_locked(standalone_journey_service: JourneyService, sample_journey: Journey):
    # node_02 depends on node_01; since node_01 is CURRENT (not COMPLETED), node_02 remains LOCKED
    standalone_journey_service.unlock_nodes_when_prerequisites_satisfied(sample_journey)
    assert sample_journey.nodes[1].state == NodeState.LOCKED
    assert sample_journey.nodes[2].state == NodeState.LOCKED
    assert sample_journey.nodes[3].state == NodeState.LOCKED


# ------------------------------------------------------------------------------
# 4. Completed Node & Prerequisite Cascade Unlocking
# ------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_completed_node_cascades_unlocking(standalone_journey_service: JourneyService, sample_journey: Journey):
    await standalone_journey_service.journey_repo.save(sample_journey)

    # Complete node_01
    updated_journey = await standalone_journey_service.update_node_state(
        journey_id=sample_journey.id,
        node_id="node_01",
        new_state=NodeState.COMPLETED
    )

    # Node 1 is COMPLETED
    assert updated_journey.nodes[0].state == NodeState.COMPLETED
    assert updated_journey.nodes[0].progress == 100

    # Node 2 prerequisites are satisfied -> Automatically promoted to CURRENT
    assert updated_journey.nodes[1].state == NodeState.CURRENT

    # Node 3 still requires Node 2, so it stays LOCKED
    assert updated_journey.nodes[2].state == NodeState.LOCKED


# ------------------------------------------------------------------------------
# 5. Mastered Node Skip
# ------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_mastered_node_skip(standalone_journey_service: JourneyService, sample_journey: Journey):
    await standalone_journey_service.journey_repo.save(sample_journey)

    # Learner already has 95% mastery on concept_dart_basics and 90% on concept_oop
    learner_mastery = {
        "concept_dart_basics": 95.0,
        "concept_oop": 90.0,
    }

    skipped_ids = await standalone_journey_service.skip_mastered_nodes(sample_journey, learner_mastery)
    assert "node_01" in skipped_ids
    assert "node_02" in skipped_ids

    assert sample_journey.nodes[0].state == NodeState.SKIPPED
    assert sample_journey.nodes[1].state == NodeState.SKIPPED

    # Since node_01 and node_02 are skipped/satisfied, node_03 unlocks to CURRENT!
    assert sample_journey.nodes[2].state == NodeState.CURRENT
    assert sample_journey.nodes[3].state == NodeState.LOCKED


# ------------------------------------------------------------------------------
# 6. Remediation Node Dynamic Insertion
# ------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_remediation_insertion(standalone_journey_service: JourneyService, sample_journey: Journey):
    await standalone_journey_service.journey_repo.save(sample_journey)

    # Learner struggles on node_03 ("Async and Streams"); insert remediation node before it
    remed_node = await standalone_journey_service.insert_remediation_nodes(
        journey_id=sample_journey.id,
        target_node_id="node_03",
        concept_id="concept_event_loop_basics",
        title="Event Loop Fundamentals",
        subtitle="Microtasks vs Event queue priority",
        estimated_minutes=15,
    )

    # Verification:
    # 1. Total nodes increased from 4 to 5
    assert len(sample_journey.nodes) == 5

    # 2. Remediation node is positioned before node_03
    remed_idx = next(i for i, n in enumerate(sample_journey.nodes) if n.id == remed_node.id)
    target_idx = next(i for i, n in enumerate(sample_journey.nodes) if n.id == "node_03")
    assert remed_idx == target_idx - 1

    # 3. Remediation node is marked CURRENT and is_remediation=True
    assert remed_node.state == NodeState.CURRENT
    assert remed_node.is_remediation is True

    # 4. Target node is now LOCKED and depends on the remediation node
    target_node = sample_journey.nodes[target_idx]
    assert target_node.state == NodeState.LOCKED
    assert remed_node.id in target_node.prerequisites
