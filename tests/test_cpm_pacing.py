import pytest
from app.services.cpm_pacing_service import cpm_pacing_service, CPMPacingService
from app.services.adag_assembler import adag_assembler


def test_calculate_capacity_hours():
    """Verify capacity math: (Days * Daily Budget) / 60."""
    assert cpm_pacing_service.calculate_capacity_hours(40, 30) == 20.0
    assert cpm_pacing_service.calculate_capacity_hours(60, 45) == 45.0
    assert cpm_pacing_service.calculate_capacity_hours(0, 30) == 0.0
    assert cpm_pacing_service.calculate_capacity_hours(30, 0) == 0.0


def test_critical_path_calculation():
    """
    Verify CPM schedules, slack, and critical path identification on a diamond graph.
    Graph:
      A (30 min) -> B (90 min) -> D (30 min)   [Total = 150 min]
      A (30 min) -> C (30 min) -> D (30 min)   [Total = 90 min]
    """
    nodes = [
        {"id": "A", "estimated_minutes": 30, "tier": "foundational"},
        {"id": "B", "estimated_minutes": 90, "tier": "core"},
        {"id": "C", "estimated_minutes": 30, "tier": "elective"},
        {"id": "D", "estimated_minutes": 30, "tier": "advanced"},
    ]
    edges = [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")]

    cpm = cpm_pacing_service.calculate_critical_path(nodes, edges)

    # Check total duration
    assert cpm["total_duration_minutes"] == 150
    assert cpm["total_duration_hours"] == 2.5

    # Critical path should be A -> B -> D
    assert cpm["critical_node_ids"] == ["A", "B", "D"]
    assert cpm["critical_path_chain"] == ["A", "B", "D"]

    # Check slack of non-critical node C
    # C earliest start = 30, latest start = 90 (since D must start at 120, C takes 30 min)
    # Slack of C = 90 - 30 = 60 minutes
    assert cpm["slack"]["C"] == 60
    assert cpm["slack"]["A"] == 0
    assert cpm["slack"]["B"] == 0
    assert cpm["slack"]["D"] == 0


def test_prune_elective_nodes_first():
    """
    Verify that elective nodes are pruned first when capacity is constrained.
    """
    nodes = [
        {"id": "A", "estimated_minutes": 60, "tier": "foundational"},
        {"id": "B", "estimated_minutes": 60, "tier": "core"},
        {"id": "C_elective_1", "estimated_minutes": 60, "tier": "elective"},
        {"id": "C_elective_2", "estimated_minutes": 60, "tier": "elective"},
        {"id": "D", "estimated_minutes": 60, "tier": "advanced"},
    ]
    # Linear chain with electives hanging off A
    edges = [
        ("A", "B"),
        ("B", "D"),
        ("A", "C_elective_1"),
        ("C_elective_1", "C_elective_2"),
        ("C_elective_2", "D"),
    ]
    # Total minutes = 300 (5 hours)
    # Give capacity of 3.2 hours (192 minutes) -> target 3 days, 64 min/day
    result = cpm_pacing_service.prune_to_fit_capacity(
        nodes=nodes,
        edges=edges,
        target_deadline_days=3,
        daily_budget_minutes=64,  # Capacity = 3 * 64 / 60 = 3.2 hours (192 mins)
    )

    pruned_nodes = result["pruned_nodes"]
    archived_ids = result["archived_node_ids"]
    pruned_edges = result["pruned_edges"]

    # Electives should be pruned
    assert "C_elective_1" in archived_ids or "C_elective_2" in archived_ids

    # Mandatory foundational & core nodes must remain!
    retained_ids = {n["id"] for n in pruned_nodes}
    assert "A" in retained_ids
    assert "B" in retained_ids
    assert "D" in retained_ids

    # Graph must be acyclic and connected
    sorted_order = adag_assembler.verify_and_sort_dag(pruned_nodes, pruned_edges)
    assert len(sorted_order) == len(pruned_nodes)
    assert ("A", "B") in pruned_edges
    assert ("B", "D") in pruned_edges


def test_prune_protects_critical_path():
    """
    Verify that nodes on the critical path with foundational/core tiers are strictly protected.
    """
    nodes = [
        {"id": "core_1", "estimated_minutes": 60, "tier": "foundational"},
        {"id": "core_2", "estimated_minutes": 60, "tier": "core"},
        {"id": "core_3", "estimated_minutes": 60, "tier": "core"},
        {"id": "adv_branch", "estimated_minutes": 60, "tier": "advanced"},
    ]
    edges = [
        ("core_1", "core_2"),
        ("core_2", "core_3"),
        ("core_1", "adv_branch"),
        ("adv_branch", "core_3"),
    ]
    # Both branches have equal duration, but core_2 is 'core' and adv_branch is 'advanced'
    # Capacity is constrained to 3 hours (180 min), total is 240 min
    result = cpm_pacing_service.prune_to_fit_capacity(
        nodes=nodes,
        edges=edges,
        target_deadline_days=3,
        daily_budget_minutes=60,  # 3.0 hours
    )

    retained_ids = {n["id"] for n in result["pruned_nodes"]}
    assert "core_1" in retained_ids
    assert "core_2" in retained_ids
    assert "core_3" in retained_ids
    # adv_branch should be archived
    assert "adv_branch" in result["archived_node_ids"]


def test_duration_compression_when_tight():
    """
    Verify duration compression activates if all nodes are retained or budget is very tight.
    """
    nodes = [
        {"id": "N1", "estimated_minutes": 60, "tier": "foundational"},
        {"id": "N2", "estimated_minutes": 60, "tier": "core"},
    ]
    edges = [("N1", "N2")]
    # Total = 120 min (2.0 hours). Capacity = 1.7 hours (102 mins)
    result = cpm_pacing_service.prune_to_fit_capacity(
        nodes=nodes,
        edges=edges,
        target_deadline_days=2,
        daily_budget_minutes=51,  # 1.7 hours
    )

    metrics = result["pacing_metrics"]
    assert metrics["compression_factor"] <= 1.0
    assert metrics["total_duration_hours"] <= 1.8
    assert result["pruned_nodes"][0]["estimated_minutes"] < 60
