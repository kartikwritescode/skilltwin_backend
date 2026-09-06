from datetime import datetime, timezone
from typing import Optional, Tuple
from app.core.logging import logger


class RetentionEngine:
    """
    Deterministic Memory Retention & Spaced Retrieval Engine for SkillTwin.
    
    Responsibilities:
    - Calculates dynamic memory retention score based on elapsed time and retrieval history.
    - Evaluates composite revision priority combining goal relevance, retention risk,
      concept importance, time elapsed since last review, and recent failure frequency.
    - Implements gradual interval expansion following successful retrievals.
    - Determines threshold-based high priority revision triggers.
    
    Note: As specified, this initial algorithm is deterministic and modular without
    claims of absolute scientific precision.
    """

    # Spaced intervals progression in days
    INTERVAL_SCHEDULE = [1, 3, 7, 14, 30, 60, 120]

    def calculate_retention_score(
        self,
        last_reviewed: Optional[datetime],
        interval_days: int,
        successful_retrievals: int = 0,
        failed_retrievals: int = 0,
        now: Optional[datetime] = None,
        last_was_failure: bool = False,
    ) -> float:
        """
        Calculates estimated memory retention percentage (0.0 to 100.0).
        Decays as time exceeds the scheduled interval, mitigated by historical successes.
        """
        now = now or datetime.now(timezone.utc)
        if not last_reviewed:
            return 50.0  # Unseen or newly queued baseline

        if last_was_failure:
            return 35.0  # Immediate post-failure retention drop

        days_elapsed = max(0.0, (now - last_reviewed).total_seconds() / 86400.0)
        target_interval = max(1, interval_days)

        # Base decay curve relative to scheduled interval
        ratio = days_elapsed / target_interval
        # Decay: 100% at ratio=0, ~50% at ratio=1.0, ~25% at ratio=2.0
        decay = min(90.0, ratio * 50.0)

        # Historical success stability bonus
        stability_bonus = min(15.0, successful_retrievals * 3.0)
        # Recent failure penalty
        failure_penalty = min(30.0, failed_retrievals * 8.0)

        score = 100.0 - decay + stability_bonus - failure_penalty
        return max(0.0, min(100.0, round(score, 1)))

    def determine_retention_risk(self, retention_score: float) -> str:
        """Maps retention score to categorical risk level."""
        if retention_score < 50.0:
            return "high"
        elif retention_score < 75.0:
            return "medium"
        return "low"

    def calculate_next_interval(
        self,
        current_interval: int,
        is_successful: bool,
        consecutive_successes: int = 0,
    ) -> int:
        """
        Gradually reduces review frequency after successful retrieval by expanding interval.
        Contracts interval back to 1 day on retrieval failure.
        """
        if not is_successful:
            return 1  # Reset to immediate next-day reinforcement

        # Find position in progression schedule or scale monotonically
        for i, val in enumerate(self.INTERVAL_SCHEDULE):
            if current_interval < val:
                return val

        # Beyond defined schedule, expand by 1.8x factor
        return max(current_interval + 7, int(current_interval * 1.8))

    def calculate_priority(
        self,
        last_reviewed: Optional[datetime],
        next_review: datetime,
        retention_score: float,
        retention_risk: str,
        is_goal_relevant: bool = True,
        concept_importance: float = 1.0,  # 0.5 to 1.5
        failed_retrievals: int = 0,
        now: Optional[datetime] = None,
    ) -> Tuple[float, bool, str]:
        """
        Combines 5 key pedagogical signals into a composite priority score (0.0 to 100.0):
        1. Goal relevance (25 pts max)
        2. Retention risk (30 pts max)
        3. Concept importance (15 pts max)
        4. Days since last review (15 pts max)
        5. Recent failures (15 pts max)

        Returns: (priority_score, is_high_priority, rationale)
        """
        now = now or datetime.now(timezone.utc)

        # 1. Goal Relevance (0 to 25 pts)
        relevance_score = 25.0 if is_goal_relevant else 5.0

        # 2. Retention Risk (0 to 30 pts)
        if retention_risk == "high":
            risk_score = 30.0
        elif retention_risk == "medium":
            risk_score = 18.0
        else:
            risk_score = 5.0

        # 3. Concept Importance (0 to 15 pts)
        importance_score = min(15.0, max(5.0, concept_importance * 10.0))

        # 4. Last Review / Overdue Urgency (0 to 15 pts)
        days_overdue = (now - next_review).total_seconds() / 86400.0
        overdue_score = min(15.0, max(0.0, days_overdue * 3.0)) if days_overdue > 0 else 2.0

        # 5. Recent Failures (0 to 15 pts)
        failure_score = min(15.0, failed_retrievals * 5.0)

        total_priority = round(
            relevance_score + risk_score + importance_score + overdue_score + failure_score,
            1,
        )

        is_high_priority = total_priority >= 65.0 or retention_risk == "high" or failure_score >= 10.0

        rationale_parts = []
        if retention_risk == "high":
            rationale_parts.append(f"retention decayed to {retention_score:.0f}%")
        if days_overdue > 0:
            rationale_parts.append(f"{days_overdue:.1f} days overdue")
        if failure_score >= 5:
            rationale_parts.append(f"{failed_retrievals} recent retrieval failures")
        if is_goal_relevant:
            rationale_parts.append("active goal milestone")

        rationale = "; ".join(rationale_parts) if rationale_parts else "Scheduled spaced reinforcement."

        return total_priority, is_high_priority, rationale


retention_engine = RetentionEngine()
