import math
from datetime import datetime, date, timedelta, timezone
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.core.database import get_session_factory
from app.core.db_models import (
    AdaptiveLearningPathModel,
    PathNodeModel,
    PathNodeEdgeModel,
    SessionModel,
)
from app.services.cpm_pacing_service import cpm_pacing_service


class PacingRecalibrationService:
    """
    Dynamic Velocity Sensor & Deadline Recalibration Engine.
    Monitors 7-day rolling velocity, calculates critical path duration drift,
    and generates proactive mentor alerts and 1-tap curriculum prune proposals.
    """

    async def calculate_rolling_velocity(
        self,
        user_id: str,
        path_id: str,
        session: Optional[AsyncSession] = None,
    ) -> Dict[str, float]:
        """
        Calculates rolling 7-day velocity:
        - Actual daily active minutes
        - Velocity factor = actual_daily_minutes / daily_budget_minutes (capped [0.2, 3.0])
        - Updates adaptive_learning_paths.velocity_factor
        """
        if session is None:
            session_factory = get_session_factory()
            async with session_factory() as sess:
                return await self.calculate_rolling_velocity(user_id, path_id, sess)

        path = await session.get(AdaptiveLearningPathModel, path_id)
        if not path:
            raise ValueError(f"AdaptiveLearningPath '{path_id}' not found")

        daily_budget = max(10, path.daily_budget_minutes or 30)

        # 1. Sum recent active study time from PathNodeModel in this path (last 7 days)
        seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
        node_stmt = select(func.sum(PathNodeModel.time_spent_minutes)).where(
            PathNodeModel.path_id == path_id,
            PathNodeModel.updated_at >= seven_days_ago,
        )
        node_minutes = (await session.execute(node_stmt)).scalar() or 0

        # Supplement with session_repository if present
        sess_minutes = 0
        try:
            from app.repositories.session_repository import session_repository
            user_sessions = await session_repository.list_by_user_id(user_id)
            sess_minutes = sum(
                round(getattr(s, "actual_duration_seconds", 0) / 60) for s in user_sessions
            )
        except Exception:
            pass

        total_active_minutes = max(node_minutes, sess_minutes)

        # Calculate average daily minutes (over 7 days, or minimum recent daily pace)
        actual_daily_minutes = round(total_active_minutes / 7.0, 1)

        # If learner has minimal history, default velocity factor to 1.0
        if actual_daily_minutes < 2.0:
            velocity_factor = 1.0
            actual_daily_minutes = float(daily_budget)
        else:
            raw_velocity = actual_daily_minutes / daily_budget
            velocity_factor = round(max(0.2, min(raw_velocity, 3.0)), 2)

        path.velocity_factor = velocity_factor
        await session.commit()

        logger.info(
            f"[PacingRecalibrationService] Updated velocity for path '{path_id}': "
            f"daily={actual_daily_minutes}m, factor={velocity_factor:.2f}"
        )

        return {
            "actual_daily_minutes": actual_daily_minutes,
            "velocity_factor": velocity_factor,
        }

    async def project_completion_timeline(
        self, path_id: str, session: Optional[AsyncSession] = None
    ) -> Dict[str, Any]:
        """
        Projects completion date by running CPM on remaining uncompleted nodes
        and dividing by actual daily study velocity.
        """
        if session is None:
            session_factory = get_session_factory()
            async with session_factory() as sess:
                return await self.project_completion_timeline(path_id, sess)

        path = await session.get(AdaptiveLearningPathModel, path_id)
        if not path:
            raise ValueError(f"AdaptiveLearningPath '{path_id}' not found")

        # Query all remaining uncompleted, non-bypassed nodes
        node_stmt = select(PathNodeModel).where(
            PathNodeModel.path_id == path_id,
            PathNodeModel.state.notin_(["COMPLETED", "BYPASSED"]),
        ).order_by(PathNodeModel.order_index)
        remaining_nodes = list((await session.execute(node_stmt)).scalars().all())

        if not remaining_nodes:
            # Everything complete!
            return {
                "path_id": path_id,
                "remaining_critical_minutes": 0,
                "daily_pace_minutes": path.daily_budget_minutes,
                "projected_days_remaining": 0,
                "projected_completion_date": date.today().isoformat(),
                "target_deadline": path.target_deadline.isoformat() if path.target_deadline else None,
                "drift_days": 0,
                "velocity_factor": path.velocity_factor or 1.0,
            }

        remaining_ids = {n.id for n in remaining_nodes}

        # Query edges between remaining nodes
        edge_stmt = select(PathNodeEdgeModel).where(
            PathNodeEdgeModel.path_id == path_id,
            PathNodeEdgeModel.source_node_id.in_(remaining_ids),
            PathNodeEdgeModel.target_node_id.in_(remaining_ids),
        )
        remaining_edges = list((await session.execute(edge_stmt)).scalars().all())

        raw_nodes = [
            {
                "id": n.id,
                "estimated_minutes": n.node_metadata.get("estimated_minutes") or 30,
                "tier": n.node_metadata.get("tier", "core"),
            }
            for n in remaining_nodes
        ]
        raw_edges = [(e.source_node_id, e.target_node_id) for e in remaining_edges]

        # Calculate Critical Path on remaining graph
        cpm = cpm_pacing_service.calculate_critical_path(raw_nodes, raw_edges)
        remaining_critical_minutes = cpm["total_duration_minutes"]

        # Calculate daily study pace factoring velocity
        velocity = path.velocity_factor or 1.0
        daily_budget = path.daily_budget_minutes or 30
        daily_pace = max(10.0, daily_budget * velocity)

        projected_days = math.ceil(remaining_critical_minutes / daily_pace)
        projected_date = date.today() + timedelta(days=projected_days)

        drift_days = 0
        if path.target_deadline:
            drift_days = (projected_date - path.target_deadline).days

        return {
            "path_id": path_id,
            "remaining_critical_minutes": remaining_critical_minutes,
            "daily_pace_minutes": round(daily_pace, 1),
            "projected_days_remaining": projected_days,
            "projected_completion_date": projected_date.isoformat(),
            "target_deadline": path.target_deadline.isoformat() if path.target_deadline else None,
            "drift_days": drift_days,
            "velocity_factor": velocity,
        }

    async def evaluate_pacing_alerts(
        self, path_id: str, session: Optional[AsyncSession] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluates pacing drift against deadline:
        - If drift > 3 days behind: generates mentor recommendation with 1-tap prune proposal.
        - If drift < -5 days ahead: proposes unlocking advanced elective enrichment.
        - Otherwise: returns None (on track).
        """
        if session is None:
            session_factory = get_session_factory()
            async with session_factory() as sess:
                return await self.evaluate_pacing_alerts(path_id, sess)

        path = await session.get(AdaptiveLearningPathModel, path_id)
        if not path or not path.target_deadline:
            return None

        projection = await self.project_completion_timeline(path_id, session)
        drift_days = projection["drift_days"]
        deadline_str = path.target_deadline.strftime("%b %d, %Y")

        # Scenario 1: Learner is falling behind deadline (> 3 days)
        if drift_days > 3:
            # Query uncompleted elective nodes that can be archived
            elective_stmt = select(PathNodeModel).where(
                PathNodeModel.path_id == path_id,
                PathNodeModel.state.notin_(["COMPLETED", "BYPASSED"]),
            )
            candidates = list((await session.execute(elective_stmt)).scalars().all())
            elective_nodes = [
                n for n in candidates
                if n.node_metadata.get("tier") == "elective" or "elective" in (n.subgraph_id or "")
            ]

            elective_count = len(elective_nodes)

            if elective_count > 0:
                msg = (
                    f"To meet your target deadline of {deadline_str}, your mentor suggests "
                    f"fast-tracking core topics and archiving {elective_count} elective modules."
                )
                action = "PRUNE_ELECTIVES"
            else:
                extra_mins = math.ceil((drift_days * (projection["daily_pace_minutes"])) / 30)
                msg = (
                    f"You are currently projected to complete {drift_days} days after your target deadline "
                    f"({deadline_str}). Consider increasing daily study time by {min(extra_mins, 30)} minutes."
                )
                action = "INCREASE_DAILY_BUDGET"

            return {
                "alert_type": "PACING_BEHIND",
                "severity": "high" if drift_days > 7 else "medium",
                "drift_days": drift_days,
                "projected_completion_date": projection["projected_completion_date"],
                "target_deadline": projection["target_deadline"],
                "elective_count": elective_count,
                "proposed_action": action,
                "message": msg,
                "quick_resolution": {
                    "action": "prune_electives",
                    "archived_count": elective_count,
                    "target_deadline": projection["target_deadline"],
                },
            }

        # Scenario 2: Learner is surging ahead (> 5 days ahead)
        if drift_days < -5:
            ahead_days = abs(drift_days)
            return {
                "alert_type": "PACING_AHEAD",
                "severity": "positive",
                "drift_days": drift_days,
                "projected_completion_date": projection["projected_completion_date"],
                "target_deadline": projection["target_deadline"],
                "proposed_action": "UNLOCK_ELECTIVES",
                "message": (
                    f"Outstanding progress! You are currently {ahead_days} days ahead of schedule for "
                    f"{deadline_str}. Your mentor has prepared optional advanced challenges and capstone projects."
                ),
            }

        # Scenario 3: On Track
        return None


pacing_recalibration_service = PacingRecalibrationService()
