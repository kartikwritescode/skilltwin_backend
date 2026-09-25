import uuid
import pytest
from datetime import date, timedelta
from app.core.database import get_session_factory, init_db
from app.core.db_models import (
    ProfileModel,
    GoalModel,
    AdaptiveLearningPathModel,
    PathNodeModel,
    PathNodeEdgeModel,
)
from app.services.pacing_recalibration_service import pacing_recalibration_service


@pytest.mark.asyncio
async def test_pacing_timeline_projection_and_behind_alert():
    """Verify projection math accurately computes drift and flags pacing behind alert."""
    await init_db()
    session_factory = get_session_factory()

    user_id = str(uuid.uuid4())
    goal_id = str(uuid.uuid4())
    path_id = str(uuid.uuid4())

    # Deadline is 5 days from today
    target_deadline = date.today() + timedelta(days=5)

    async with session_factory() as session:
        profile = ProfileModel(id=user_id, display_name="Drifting Learner")
        goal = GoalModel(id=goal_id, user_id=user_id, title="Exam Goal")
        path = AdaptiveLearningPathModel(
            id=path_id,
            user_id=user_id,
            goal_id=goal_id,
            title="Certification Path",
            target_deadline=target_deadline,
            daily_budget_minutes=30,
            velocity_factor=0.5,  # Moving at half speed (15 min/day)
        )

        # 3 Core nodes (60 min each = 180 min total critical path)
        # At 15 min/day -> 180 / 15 = 12 days to complete!
        # Target deadline is in 5 days -> drift = 12 - 5 = +7 days behind!
        node1 = PathNodeModel(
            id=f"n_{uuid.uuid4().hex[:8]}", path_id=path_id, concept_id="c_core_1",
            title="Core Module 1", state="AVAILABLE", order_index=0,
            node_metadata={"estimated_minutes": 60, "tier": "core"},
        )
        node2 = PathNodeModel(
            id=f"n_{uuid.uuid4().hex[:8]}", path_id=path_id, concept_id="c_core_2",
            title="Core Module 2", state="LOCKED", order_index=1,
            node_metadata={"estimated_minutes": 60, "tier": "core"},
        )
        node3 = PathNodeModel(
            id=f"n_{uuid.uuid4().hex[:8]}", path_id=path_id, concept_id="c_core_3",
            title="Core Module 3", state="LOCKED", order_index=2,
            node_metadata={"estimated_minutes": 60, "tier": "core"},
        )
        # 2 Elective nodes
        node4 = PathNodeModel(
            id=f"n_{uuid.uuid4().hex[:8]}", path_id=path_id, concept_id="c_elective_1",
            title="Elective Deep Dive", state="LOCKED", order_index=3,
            node_metadata={"estimated_minutes": 45, "tier": "elective"},
        )

        edge1 = PathNodeEdgeModel(
            id=f"e_{uuid.uuid4().hex[:8]}", path_id=path_id, source_node_id=node1.id, target_node_id=node2.id
        )
        edge2 = PathNodeEdgeModel(
            id=f"e_{uuid.uuid4().hex[:8]}", path_id=path_id, source_node_id=node2.id, target_node_id=node3.id
        )

        session.add_all([profile, goal, path, node1, node2, node3, node4, edge1, edge2])
        await session.commit()

    # Test projection
    async with session_factory() as session:
        proj = await pacing_recalibration_service.project_completion_timeline(path_id, session)
        assert proj["remaining_critical_minutes"] >= 180
        assert proj["drift_days"] > 3

        # Test alert evaluation
        alert = await pacing_recalibration_service.evaluate_pacing_alerts(path_id, session)
        assert alert is not None
        assert alert["alert_type"] == "PACING_BEHIND"
        assert alert["drift_days"] > 3
        assert alert["elective_count"] >= 1
        assert alert["proposed_action"] == "PRUNE_ELECTIVES"
        assert "suggests fast-tracking core topics" in alert["message"]
        assert alert["quick_resolution"]["action"] == "prune_electives"


@pytest.mark.asyncio
async def test_pacing_ahead_alert():
    """Verify ahead-of-schedule learner receives positive enrichment alert."""
    session_factory = get_session_factory()

    user_id = str(uuid.uuid4())
    goal_id = str(uuid.uuid4())
    path_id = str(uuid.uuid4())

    # Deadline is 30 days away, but only 1 short module remaining (30 min)
    target_deadline = date.today() + timedelta(days=30)

    async with session_factory() as session:
        profile = ProfileModel(id=user_id, display_name="Fast Learner")
        goal = GoalModel(id=goal_id, user_id=user_id, title="Swift Goal")
        path = AdaptiveLearningPathModel(
            id=path_id,
            user_id=user_id,
            goal_id=goal_id,
            title="Fast Path",
            target_deadline=target_deadline,
            daily_budget_minutes=60,
            velocity_factor=2.0,  # 120 min/day pace
        )
        node = PathNodeModel(
            id=f"n_{uuid.uuid4().hex[:8]}", path_id=path_id, concept_id="c_final",
            title="Final Checkpoint", state="AVAILABLE", order_index=0,
            node_metadata={"estimated_minutes": 30, "tier": "core"},
        )
        session.add_all([profile, goal, path, node])
        await session.commit()

    async with session_factory() as session:
        alert = await pacing_recalibration_service.evaluate_pacing_alerts(path_id, session)
        assert alert is not None
        assert alert["alert_type"] == "PACING_AHEAD"
        assert alert["drift_days"] < -5
        assert "ahead of schedule" in alert["message"].lower()


@pytest.mark.asyncio
async def test_calculate_rolling_velocity():
    """Verify rolling velocity calculates accurately and caps between [0.2, 3.0]."""
    session_factory = get_session_factory()

    user_id = str(uuid.uuid4())
    goal_id = str(uuid.uuid4())
    path_id = str(uuid.uuid4())

    async with session_factory() as session:
        profile = ProfileModel(id=user_id, display_name="Velocity Learner")
        goal = GoalModel(id=goal_id, user_id=user_id, title="Velocity Goal")
        path = AdaptiveLearningPathModel(
            id=path_id, user_id=user_id, goal_id=goal_id, title="Velocity Path",
            daily_budget_minutes=30,
        )
        # Completed node with 140 minutes spent
        node = PathNodeModel(
            id=f"n_{uuid.uuid4().hex[:8]}", path_id=path_id, concept_id="c_spent",
            title="Topic Spent", state="COMPLETED", order_index=0,
            time_spent_minutes=140,
        )
        session.add_all([profile, goal, path, node])
        await session.commit()

    async with session_factory() as session:
        res = await pacing_recalibration_service.calculate_rolling_velocity(user_id, path_id, session)
        assert "actual_daily_minutes" in res
        assert "velocity_factor" in res
        assert 0.2 <= res["velocity_factor"] <= 3.0
