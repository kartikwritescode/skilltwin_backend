from typing import Optional, List, Dict
from app.repositories.base import BaseRepository
from app.domain.journeys.models import Journey, JourneyNode


class JourneyRepository(BaseRepository[Journey, str]):
    def __init__(self):
        self._journeys: Dict[str, Journey] = {}

    async def get_by_id(self, entity_id: str) -> Optional[Journey]:
        return self._journeys.get(entity_id)

    async def get_by_goal_id(self, goal_id: str) -> Optional[Journey]:
        for j in self._journeys.values():
            if j.goal_id == goal_id:
                return j
        return None

    async def list_all(self) -> List[Journey]:
        return list(self._journeys.values())

    async def save(self, entity: Journey) -> Journey:
        self._journeys[entity.id] = entity
        return entity

    async def update_node_state(self, journey_id: str, node_id: str, new_state) -> Optional[JourneyNode]:
        journey = self._journeys.get(journey_id)
        if not journey:
            return None
        for node in journey.nodes:
            if node.id == node_id:
                node.state = new_state
                return node
        return None

    async def delete(self, entity_id: str) -> bool:
        if entity_id in self._journeys:
            del self._journeys[entity_id]
            return True
        return False


journey_repository = JourneyRepository()
