from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Tuple
from app.domain.learner.models import (
    LearnerConceptState,
    RetentionRisk,
    LearnerConceptStatus,
    Misconception,
    MisconceptionStatus,
)


class LearnerRepository:
    """Manages Learner Twin persistence: concept states and detected misconceptions."""

    def __init__(self):
        # Key: (user_id, concept_id) -> LearnerConceptState
        self._states: Dict[Tuple[str, str], LearnerConceptState] = {}
        # Key: misconception_id -> Misconception
        self._misconceptions: Dict[str, Misconception] = {}
        self._seed_sample_learner_state()

    def _seed_sample_learner_state(self):
        # Seed default state for concept_recursion as highlighted in the spec
        user_id = "default_learner_01"
        concept_id = "concept_recursion"
        now = datetime.now(timezone.utc)
        self._states[(user_id, concept_id)] = LearnerConceptState(
            user_id=user_id,
            concept_id=concept_id,
            mastery_score=78.0,
            confidence_score=65.0,
            retention_score=35.0,
            risk_score=72.0,
            status=LearnerConceptStatus.NEEDS_REVIEW,
            misconception_tags=["base_case_termination"],
            evidence_count=3,
            last_seen_at=now - timedelta(days=9),
            next_review_at=now - timedelta(hours=2),
            updated_at=now,
        )

    async def get_concept_state(self, user_id: str, concept_id: str) -> Optional[LearnerConceptState]:
        return self._states.get((user_id, concept_id))

    async def save_concept_state(self, state: LearnerConceptState) -> LearnerConceptState:
        state.updated_at = datetime.now(timezone.utc)
        self._states[(state.user_id, state.concept_id)] = state
        return state

    async def list_states_for_user(self, user_id: str) -> List[LearnerConceptState]:
        return [s for (u, _), s in self._states.items() if u == user_id]

    async def list_all(self) -> List[LearnerConceptState]:
        return list(self._states.values())

    async def list_misconceptions_for_concept(
        self, user_id: str, concept_id: str, active_only: bool = True
    ) -> List[Misconception]:
        results = [
            m for m in self._misconceptions.values()
            if m.user_id == user_id and m.concept_id == concept_id
        ]
        if active_only:
            results = [m for m in results if m.status == MisconceptionStatus.ACTIVE]
        return results

    async def list_all_misconceptions_for_user(
        self, user_id: str, active_only: bool = True
    ) -> List[Misconception]:
        results = [m for m in self._misconceptions.values() if m.user_id == user_id]
        if active_only:
            results = [m for m in results if m.status == MisconceptionStatus.ACTIVE]
        return results

    async def save_misconception(self, misconception: Misconception) -> Misconception:
        self._misconceptions[misconception.id] = misconception
        return misconception


# LearnerStateRepository alias as requested in specification
LearnerStateRepository = LearnerRepository
learner_repository = LearnerRepository()
learner_state_repository = learner_repository
