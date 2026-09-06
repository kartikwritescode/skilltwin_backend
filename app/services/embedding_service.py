from typing import List, Optional
from app.ai.providers.base import LLMProvider
from app.ai.providers.factory import get_llm_provider
from app.core.logging import logger

class EmbeddingService:
    def __init__(self, llm_provider: Optional[LLMProvider] = None):
        self.llm_provider = llm_provider or get_llm_provider()

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        logger.info(f"Generating vector embeddings for {len(texts)} chunks")
        return await self.llm_provider.embed(texts)

    async def embed_query(self, query: str) -> List[float]:
        results = await self.llm_provider.embed([query])
        return results[0] if results else []

embedding_service = EmbeddingService()
