from typing import Optional, List, Dict
from app.repositories.base import BaseRepository
from app.domain.sessions.models import LearningSession, EvidenceRecord


class SessionRepository(BaseRepository[LearningSession, str]):
    def __init__(self):
        self._sessions: Dict[str, LearningSession] = {}
        self._evidence: Dict[str, EvidenceRecord] = {}

    async def get_by_id(self, entity_id: str) -> Optional[LearningSession]:
        return self._sessions.get(entity_id)

    async def list_all(self) -> List[LearningSession]:
        return list(self._sessions.values())

    async def list_by_user_id(self, user_id: str) -> List[LearningSession]:
        return [s for s in self._sessions.values() if s.user_id == user_id]

    async def save(self, entity: LearningSession) -> LearningSession:
        self._sessions[entity.id] = entity
        return entity

    async def save_evidence(self, evidence: EvidenceRecord) -> EvidenceRecord:
        self._evidence[evidence.id] = evidence
        return evidence

    async def list_evidence_for_concept(self, user_id: str, concept_id: str) -> List[EvidenceRecord]:
        return [
            e for e in self._evidence.values()
            if e.user_id == user_id and e.concept_id == concept_id
        ]

    async def delete(self, entity_id: str) -> bool:
        if entity_id in self._sessions:
            del self._sessions[entity_id]
            return True
        return False


session_repository = SessionRepository()
