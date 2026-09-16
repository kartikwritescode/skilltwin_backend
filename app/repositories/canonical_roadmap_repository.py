import math
from typing import Optional, List, Dict, Tuple
from app.repositories.base import BaseRepository
from app.core.db_models import CanonicalRoadmapModel, CanonicalNodeModel


class CanonicalRoadmapRepository(BaseRepository[CanonicalRoadmapModel, str]):
    """
    Repository for Canonical Technology Roadmaps and their Nodes.
    Supports in-memory access and vector cosine similarity search.
    """

    def __init__(self):
        self._roadmaps: Dict[str, CanonicalRoadmapModel] = {}

    async def get_by_id(self, entity_id: str) -> Optional[CanonicalRoadmapModel]:
        return self._roadmaps.get(entity_id)

    async def get_by_slug(self, slug: str) -> Optional[CanonicalRoadmapModel]:
        target = slug.lower().strip()
        for r in self._roadmaps.values():
            if r.slug.lower() == target:
                return r

        # Common slug aliases
        alias_map = {
            "flutter": "flutter_mobile",
            "python": "python_backend",
            "fullstack": "fullstack_web",
            "dsa": "dsa_problem_solving",
            "ml": "machine-learning",
            "ai": "ai-engineer",
            "ux": "ux-design",
            "pm": "product-manager",
            "em": "engineering-manager",
            "fde": "forward-deployed-engineer",
        }
        if target in alias_map:
            aliased = alias_map[target]
            for r in self._roadmaps.values():
                if r.slug.lower() == aliased:
                    return r

        # Prefix/suffix fallback
        for r in self._roadmaps.values():
            if r.slug.lower().startswith(target) or target.startswith(r.slug.lower()):
                return r
        return None

    async def list_all(self, active_only: bool = True) -> List[CanonicalRoadmapModel]:
        if active_only:
            return [r for r in self._roadmaps.values() if r.is_active]
        return list(self._roadmaps.values())

    async def save(self, entity: CanonicalRoadmapModel) -> CanonicalRoadmapModel:
        self._roadmaps[entity.id] = entity
        return entity

    async def delete(self, entity_id: str) -> bool:
        if entity_id in self._roadmaps:
            del self._roadmaps[entity_id]
            return True
        return False

    async def similarity_search(
        self,
        query_embedding: List[float],
        query_text: Optional[str] = None,
        top_k: int = 3,
        threshold: float = 0.0,
    ) -> List[Tuple[CanonicalRoadmapModel, float]]:
        """
        Calculates hybrid similarity (cosine similarity + lexical tag/keyword overlap).
        Returns top_k matches exceeding the threshold, sorted descending by similarity score.
        """
        if not query_embedding and not query_text:
            return []

        norm_q = math.sqrt(sum(a * a for a in query_embedding)) if query_embedding else 0.0

        query_tokens = (
            set(query_text.lower().replace("-", " ").replace("_", " ").split())
            if query_text
            else set()
        )

        scored: List[Tuple[CanonicalRoadmapModel, float]] = []
        for roadmap in self._roadmaps.values():
            if not roadmap.is_active:
                continue

            # 1. Vector cosine similarity
            emb_score = 0.0
            if norm_q > 0.0 and roadmap.embedding:
                emb = roadmap.embedding
                norm_r = math.sqrt(sum(b * b for b in emb))
                if norm_r > 0.0:
                    dot = sum(a * b for a, b in zip(query_embedding, emb))
                    emb_score = max(0.0, dot / (norm_q * norm_r))

            # 2. Lexical keyword / tag / slug overlap
            lex_score = 0.0
            if query_tokens:
                slug_tokens = set(roadmap.slug.lower().replace("-", " ").replace("_", " ").split())
                slug_match = bool(slug_tokens & query_tokens) or (roadmap.slug.lower() in query_tokens)
                title_tokens = set(roadmap.title.lower().replace("-", " ").replace("_", " ").split())
                tag_tokens = {t.lower() for t in (roadmap.tags or [])}
                matched_tags = tag_tokens & query_tokens

                if slug_match:
                    # Direct slug match (e.g. "flutter", "python", "dsa", "fullstack")
                    lex_score = 1.0 + (0.1 * len(matched_tags))
                elif matched_tags:
                    # Proportional to tag matches
                    lex_score = min(0.9, 0.4 + 0.25 * len(matched_tags))
                elif title_tokens & query_tokens:
                    lex_score = 0.35

            # Combined hybrid score (semantic vector + lexical grounding)
            if query_tokens and norm_q > 0.0:
                final_score = 0.5 * emb_score + 0.5 * min(1.0, lex_score)
                if slug_match:
                    final_score = max(final_score, 0.95)
                elif lex_score >= 0.65:
                    final_score = max(final_score, 0.85)
            elif norm_q > 0.0:
                final_score = emb_score
            else:
                final_score = lex_score

            if final_score >= threshold:
                scored.append((roadmap, final_score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


canonical_roadmap_repository = CanonicalRoadmapRepository()
