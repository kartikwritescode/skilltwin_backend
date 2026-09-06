from typing import Optional, List
from app.ai.providers.base import LLMProvider
from app.ai.providers.factory import get_llm_provider
from app.ai.schemas.ai_schemas import ExtractedConceptList, ExtractedConcept
from app.core.logging import logger

CONCEPT_EXTRACTION_PROMPT = """
Analyze the following educational text and extract the key concepts.
Return structured concepts including name, clear description, difficulty level, and prerequisites.

Text:
{text}
"""

class ConceptExtractor:
    def __init__(self, llm_provider: Optional[LLMProvider] = None):
        self.llm_provider = llm_provider or get_llm_provider()

    async def extract_concepts(self, text: str, max_chars: int = 4000) -> ExtractedConceptList:
        sample_text = text[:max_chars]
        logger.info(f"Extracting structured concepts from text ({len(sample_text)} chars)")
        prompt = CONCEPT_EXTRACTION_PROMPT.format(text=sample_text)
        result = await self.llm_provider.generate_structured(
            prompt=prompt,
            response_schema=ExtractedConceptList,
            system_prompt="You are an expert curriculum taxonomist and knowledge graph architect."
        )
        return result

concept_extractor = ConceptExtractor()
