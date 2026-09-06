from functools import lru_cache
from app.ai.providers.base import LLMProvider
from app.ai.providers.mock_provider import MockLLMProvider
from app.ai.providers.gemini_provider import GeminiLLMProvider
from app.core.config import settings
from app.core.logging import logger


@lru_cache()
def get_llm_provider() -> LLMProvider:
    """
    Factory function returning the configured LLMProvider instance.
    Defaults to MockLLMProvider for offline runs and mock mode.
    Seamlessly uses live GeminiLLMProvider when configured.
    """
    provider_name = settings.LLM_PROVIDER.lower()
    logger.info(f"Instantiating LLM Provider: {provider_name}")

    if provider_name == "mock":
        return MockLLMProvider()

    if provider_name in ["gemini", "google"]:
        logger.info(f"Initializing Gemini LLM Provider (model: {settings.LLM_MODEL})")
        return GeminiLLMProvider(
            api_key=settings.LLM_API_KEY,
            model=settings.LLM_MODEL,
        )

    logger.warning(f"Unknown LLM_PROVIDER '{provider_name}', falling back to MockLLMProvider")
    return MockLLMProvider()
