import time
import pytest
from app.core.db_models import MicroSubgraphModel
from app.services.adag_assembler import (
    TopologicalAssembler,
    CyclicDependencyError,
    MissingPrerequisiteError,
    adag_assembler,
)


def test_linear_dependency_sort():
    """Verify linear topological ordering: A -> B -> C -> D."""
    nodes = [{"id": "A"}, {"id": "B"}, {"id": "C"}, {"id": "D"}]
    edges = [("A", "B"), ("B", "C"), ("C", "D")]

    sorted_order = adag_assembler.verify_and_sort_dag(nodes, edges)
    assert sorted_order == ["A", "B", "C", "D"]


def test_diamond_graph_multi_branch():
    """Verify multi-branch DAG (diamond): A -> B, A -> C, B -> D, C -> D."""
    nodes = [{"id": "A"}, {"id": "B"}, {"id": "C"}, {"id": "D"}]
    edges = [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")]

    sorted_order = adag_assembler.verify_and_sort_dag(nodes, edges)
    assert sorted_order[0] == "A"
    assert sorted_order[-1] == "D"
    assert set(sorted_order[1:3]) == {"B", "C"}


def test_cycle_detection_raises_error():
    """Verify cycle detection raises CyclicDependencyError with cycle path details."""
    nodes = [{"id": "A"}, {"id": "B"}, {"id": "C"}, {"id": "D"}]
    # A -> B -> C -> A (cycle!) and C -> D
    edges = [("A", "B"), ("B", "C"), ("C", "A"), ("C", "D")]

    with pytest.raises(CyclicDependencyError) as exc_info:
        adag_assembler.verify_and_sort_dag(nodes, edges)

    err_msg = str(exc_info.value)
    assert "cyclic dependencies" in err_msg.lower()
    assert "A" in err_msg and "B" in err_msg and "C" in err_msg


def test_missing_prerequisite_raises_error():
    """Verify missing node reference raises MissingPrerequisiteError."""
    nodes = [{"id": "A"}, {"id": "B"}]
    edges = [("A", "NON_EXISTENT_NODE")]

    with pytest.raises(MissingPrerequisiteError):
        adag_assembler.verify_and_sort_dag(nodes, edges)


def test_transitive_reduction():
    """Verify transitive reduction eliminates shortcut redundant edges."""
    # Graph: A -> B, B -> C, A -> C (shortcut), C -> D, A -> D (shortcut)
    nodes = ["A", "B", "C", "D"]
    edges = {("A", "B"), ("B", "C"), ("A", "C"), ("C", "D"), ("A", "D")}

    reduced = adag_assembler.transitive_reduction(nodes, edges)

    # A -> C and A -> D should be eliminated
    assert ("A", "C") not in reduced
    assert ("A", "D") not in reduced

    # Essential edges must remain
    assert ("A", "B") in reduced
    assert ("B", "C") in reduced
    assert ("C", "D") in reduced
    assert len(reduced) == 3


def test_assembly_performance_100_nodes():
    """Verify that topological sorting and reduction for 100+ nodes executes in < 15ms."""
    node_count = 120
    nodes = [{"id": f"node_{i}"} for i in range(node_count)]
    edges = []

    # Build layered DAG with some multi-branches and shortcuts
    for i in range(node_count - 1):
        edges.append((f"node_{i}", f"node_{i+1}"))
        if i + 2 < node_count and i % 3 == 0:
            edges.append((f"node_{i}", f"node_{i+2}"))  # shortcut edge

    start_time = time.perf_counter()

    sorted_ids = adag_assembler.verify_and_sort_dag(nodes, edges)
    reduced_edges = adag_assembler.transitive_reduction(sorted_ids, set(edges))

    duration_ms = (time.perf_counter() - start_time) * 1000

    assert len(sorted_ids) == node_count
    assert duration_ms < 15.0, f"Assembly took {duration_ms:.2f}ms, expected < 15ms"


def test_stitch_subgraphs():
    """Verify stitch_subgraphs correctly connects micro-subgraphs and resolves initial states."""
    sg1 = MicroSubgraphModel(
        id="sub_html",
        slug="html-basics",
        title="HTML5 Foundations",
        tier="foundational",
        estimated_minutes=45,
        prerequisites=[],
    )
    sg2 = MicroSubgraphModel(
        id="sub_css",
        slug="css-styling",
        title="CSS Styling & Layouts",
        tier="core",
        estimated_minutes=60,
        prerequisites=["html-basics"],
    )
    sg3 = MicroSubgraphModel(
        id="sub_js",
        slug="javascript-dom",
        title="JavaScript DOM Manipulation",
        tier="core",
        estimated_minutes=75,
        prerequisites=["html-basics", "css-styling"],  # css-styling depends on html-basics, so html-basics is a shortcut
    )

    nodes, edges = adag_assembler.stitch_subgraphs([sg1, sg2, sg3])

    assert len(nodes) == 3
    # Check topological order
    assert nodes[0]["id"] == "html-basics__core"
    assert nodes[0]["order_index"] == 0
    assert nodes[0]["state"] == "AVAILABLE"  # Root node is AVAILABLE

    assert nodes[1]["id"] == "css-styling__core"
    assert nodes[1]["order_index"] == 1
    assert nodes[1]["state"] == "LOCKED"

    assert nodes[2]["id"] == "javascript-dom__core"
    assert nodes[2]["order_index"] == 2
    assert nodes[2]["state"] == "LOCKED"

    # Transitive reduction should remove html-basics -> javascript-dom
    assert ("html-basics__core", "javascript-dom__core") not in edges
    assert ("html-basics__core", "css-styling__core") in edges
    assert ("css-styling__core", "javascript-dom__core") in edges
