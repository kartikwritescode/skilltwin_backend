from typing import Optional, List, Dict
from app.repositories.base import BaseRepository
from app.domain.mentor.models import RecommendationRecord


class RecommendationRepository(BaseRepository[RecommendationRecord, str]):
    """Stores persistent audit log of all recommendations generated for learners."""

    def __init__(self):
        self._recommendations: Dict[str, RecommendationRecord] = {}

    async def get_by_id(self, entity_id: str) -> Optional[RecommendationRecord]:
        return self._recommendations.get(entity_id)

    async def list_all(self) -> List[RecommendationRecord]:
        return list(self._recommendations.values())

    async def list_by_user_id(self, user_id: str, limit: int = 50) -> List[RecommendationRecord]:
        user_recs = [r for r in self._recommendations.values() if r.user_id == user_id]
        user_recs.sort(key=lambda x: x.created_at, reverse=True)
        return user_recs[:limit]

    async def save(self, entity: RecommendationRecord) -> RecommendationRecord:
        self._recommendations[entity.id] = entity
        return entity

    async def delete(self, entity_id: str) -> bool:
        if entity_id in self._recommendations:
            del self._recommendations[entity_id]
            return True
        return False


recommendation_repository = RecommendationRepository()
