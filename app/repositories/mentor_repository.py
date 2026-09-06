from typing import Optional, List, Dict
from app.repositories.base import BaseRepository
from app.domain.mentor.models import MentorMessage


class MentorRepository(BaseRepository[MentorMessage, str]):
    def __init__(self):
        self._messages: Dict[str, MentorMessage] = {}

    async def get_by_id(self, entity_id: str) -> Optional[MentorMessage]:
        return self._messages.get(entity_id)

    async def list_all(self) -> List[MentorMessage]:
        return list(self._messages.values())

    async def list_by_user_id(self, user_id: str, limit: int = 50) -> List[MentorMessage]:
        user_msgs = [m for m in self._messages.values() if m.user_id == user_id]
        user_msgs.sort(key=lambda m: m.created_at)
        return user_msgs[-limit:]

    async def save(self, entity: MentorMessage) -> MentorMessage:
        self._messages[entity.id] = entity
        return entity

    async def delete(self, entity_id: str) -> bool:
        if entity_id in self._messages:
            del self._messages[entity_id]
            return True
        return False


mentor_repository = MentorRepository()
