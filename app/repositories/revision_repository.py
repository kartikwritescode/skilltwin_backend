from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict
from app.repositories.base import BaseRepository
from app.domain.revision.models import ReviewItem


class RevisionRepository(BaseRepository[ReviewItem, str]):
    def __init__(self):
        self._items: Dict[str, ReviewItem] = {}
        self._seed_default_revision_items()

    def _seed_default_revision_items(self):
        # Seed revision cards from product spec:
        # RECURSION (Overdue, high risk, priority)
        now = datetime.now(timezone.utc)
        item1 = ReviewItem(
            id="rev_recursion_01",
            user_id="default_learner_01",
            concept_id="concept_recursion",
            concept_name="Recursion",
            next_review=now - timedelta(hours=2),  # Overdue
            interval=4,
            last_reviewed=now - timedelta(days=9),
            successful_retrievals=2,
            failed_retrievals=1,
            retention_score=38.0,
            priority_score=85.0,
            is_high_priority=True,
            retention_risk="high",
            why_today="Retention risk is high. Last strong retrieval was 9 days ago. Rapid retrieval anchors recursive base case invariants.",
            mentor_prompt="Give me 4 minutes. I want to check whether the mental model is still intact.",
            estimated_minutes=4,
        )
        self._items[item1.id] = item1

        item2 = ReviewItem(
            id="rev_streams_02",
            user_id="default_learner_01",
            concept_id="concept_dart_async_and_streams",
            concept_name="Dart Async & Streams",
            next_review=now - timedelta(minutes=10),
            interval=3,
            last_reviewed=now - timedelta(days=4),
            successful_retrievals=1,
            failed_retrievals=0,
            retention_score=62.0,
            priority_score=60.0,
            is_high_priority=False,
            retention_risk="medium",
            why_today="StreamController disposal pattern and broadcast listeners due for scheduled spaced review.",
            mentor_prompt="Recall the difference between single-subscription and broadcast streams.",
            estimated_minutes=5,
        )
        self._items[item2.id] = item2

    async def get_by_id(self, entity_id: str) -> Optional[ReviewItem]:
        return self._items.get(entity_id)

    async def list_all(self) -> List[ReviewItem]:
        return list(self._items.values())

    async def list_due_for_user(self, user_id: str) -> List[ReviewItem]:
        now = datetime.now(timezone.utc)
        due = [
            item for item in self._items.values()
            if item.user_id == user_id and item.next_review <= now
        ]
        due.sort(key=lambda x: x.next_review)
        return due

    async def save(self, entity: ReviewItem) -> ReviewItem:
        self._items[entity.id] = entity
        return entity

    async def delete(self, entity_id: str) -> bool:
        if entity_id in self._items:
            del self._items[entity_id]
            return True
        return False


revision_repository = RevisionRepository()
