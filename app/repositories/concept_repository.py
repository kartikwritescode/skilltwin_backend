from typing import Optional, List, Dict
from app.repositories.base import BaseRepository
from app.domain.concepts.models import Concept


class ConceptRepository(BaseRepository[Concept, str]):
    def __init__(self):
        self._concepts: Dict[str, Concept] = {}
        self._seed_default_concepts()

    def _seed_default_concepts(self):
        sample_concepts = [
            Concept(
                id="concept_dart_async_and_streams",
                name="Dart Async & Streams",
                description="Understand StreamControllers, Futures, microtask queues, and asynchronous event handling.",
                domain="Flutter",
                difficulty_level="intermediate",
                prerequisites=["dart_basics"],
            ),
            Concept(
                id="concept_recursion",
                name="Recursion",
                description="Solving problems by breaking them down into smaller sub-problems with invariant base cases.",
                domain="Computer Science",
                difficulty_level="intermediate",
                prerequisites=["functions", "stack_memory"],
            ),
            Concept(
                id="concept_state_management",
                name="State Management Architecture",
                description="Predictable unidirectional data flow, caching, and reactivity using Riverpod / Bloc.",
                domain="Flutter",
                difficulty_level="advanced",
                prerequisites=["concept_dart_async_and_streams"],
            )
        ]
        for c in sample_concepts:
            self._concepts[c.id] = c

    async def get_by_id(self, entity_id: str) -> Optional[Concept]:
        return self._concepts.get(entity_id)

    async def get_by_name_or_id(self, identifier: str) -> Optional[Concept]:
        if identifier in self._concepts:
            return self._concepts[identifier]
        for c in self._concepts.values():
            if c.name.lower() == identifier.lower():
                return c
        return None

    async def list_all(self) -> List[Concept]:
        return list(self._concepts.values())

    async def save(self, entity: Concept) -> Concept:
        self._concepts[entity.id] = entity
        return entity

    async def delete(self, entity_id: str) -> bool:
        if entity_id in self._concepts:
            del self._concepts[entity_id]
            return True
        return False


concept_repository = ConceptRepository()
