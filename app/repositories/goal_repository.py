from typing import Optional, List, Dict
from app.repositories.base import BaseRepository
from app.domain.goals.models import Goal


class GoalRepository(BaseRepository[Goal, str]):
    def __init__(self):
        # In-memory storage backing domain repository for standalone local execution
        self._goals: Dict[str, Goal] = {}

    async def get_by_id(self, entity_id: str) -> Optional[Goal]:
        return self._goals.get(entity_id)

    async def list_all(self) -> List[Goal]:
        return list(self._goals.values())

    async def list_by_user_id(self, user_id: str) -> List[Goal]:
        return [g for g in self._goals.values() if g.user_id == user_id]

    async def get_active_goal_for_user(self, user_id: str) -> Optional[Goal]:
        for g in self._goals.values():
            if g.user_id == user_id and g.status.value == "active":
                return g
        return None

    async def save(self, entity: Goal) -> Goal:
        self._goals[entity.id] = entity
        return entity

    async def delete(self, entity_id: str) -> bool:
        if entity_id in self._goals:
            del self._goals[entity_id]
            return True
        return False


# Singleton instance for repository dependency injection
goal_repository = GoalRepository()
