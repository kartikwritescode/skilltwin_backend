import math
from typing import Optional, List, Dict
from app.repositories.base import BaseRepository
from app.domain.resources.models import Resource, ResourceChunk


class ResourceRepository(BaseRepository[Resource, str]):
    def __init__(self):
        self._resources: Dict[str, Resource] = {}
        self._chunks: Dict[str, ResourceChunk] = {}

    async def get_by_id(self, entity_id: str) -> Optional[Resource]:
        return self._resources.get(entity_id)

    async def list_all(self) -> List[Resource]:
        return list(self._resources.values())

    async def list_for_user(self, user_id: str, include_public: bool = True) -> List[Resource]:
        return [
            r for r in self._resources.values()
            if r.user_id == user_id or (include_public and r.is_public)
        ]

    async def save(self, entity: Resource) -> Resource:
        self._resources[entity.id] = entity
        return entity

    async def delete(self, entity_id: str) -> bool:
        if entity_id in self._resources:
            del self._resources[entity_id]
            # Delete associated chunks
            chunk_ids = [cid for cid, c in self._chunks.items() if c.resource_id == entity_id]
            for cid in chunk_ids:
                del self._chunks[cid]
            return True
        return False

    async def save_chunk(self, chunk: ResourceChunk) -> ResourceChunk:
        self._chunks[chunk.id] = chunk
        return chunk

    async def get_chunk_by_id(self, chunk_id: str) -> Optional[ResourceChunk]:
        return self._chunks.get(chunk_id)

    async def list_chunks_for_resource(self, resource_id: str) -> List[ResourceChunk]:
        chunks = [c for c in self._chunks.values() if c.resource_id == resource_id]
        chunks.sort(key=lambda x: x.chunk_index)
        return chunks

    async def similarity_search(
        self,
        query_embedding: List[float],
        user_id: str,
        concept_id: Optional[str] = None,
        top_k: int = 4,
    ) -> List[tuple[ResourceChunk, float]]:
        accessible_resource_ids = {
            r.id for r in self._resources.values()
            if r.user_id == user_id or r.is_public
        }

        candidates = [
            c for c in self._chunks.values()
            if c.resource_id in accessible_resource_ids
            and (concept_id is None or c.concept_id == concept_id)
        ]

        scored_chunks = []
        for c in candidates:
            if not c.embedding or not query_embedding:
                score = 0.0
            else:
                dot_product = sum(a * b for a, b in zip(query_embedding, c.embedding))
                norm_a = math.sqrt(sum(a * a for a in query_embedding))
                norm_b = math.sqrt(sum(b * b for b in c.embedding))
                score = dot_product / (norm_a * norm_b) if norm_a and norm_b else 0.0
            scored_chunks.append((c, score))

        scored_chunks.sort(key=lambda x: x[1], reverse=True)
        return scored_chunks[:top_k]


resource_repository = ResourceRepository()
