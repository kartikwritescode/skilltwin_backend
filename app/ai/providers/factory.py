from functools import lru_cache
from app.ai.providers.base import LLMProvider
from app.ai.providers.mock_provider import MockLLMProvider
from app.core.config import settings
from app.core.logging import logger


@lru_cache()
def get_llm_provider() -> LLMProvider:
    """
    Factory function returning the configured LLMProvider instance.
    Defaults to MockLLMProvider for offline runs, local tests, and mock mode.
    Can seamlessly plug in GeminiProvider or OpenAIProvider when configured.
    """
    provider_name = settings.LLM_PROVIDER.lower()
    logger.info(f"Instantiating LLM Provider: {provider_name}")

    if provider_name == "mock":
        return MockLLMProvider()

    # Vendor expansion points:
    # elif provider_name == "gemini":
    #     return GeminiLLMProvider(api_key=settings.LLM_API_KEY, model=settings.LLM_MODEL)
    # elif provider_name == "openai":
    #     return OpenAILLMProvider(api_key=settings.LLM_API_KEY, model=settings.LLM_MODEL)

    logger.warning(f"Unknown LLM_PROVIDER '{provider_name}', falling back to MockLLMProvider")
    return MockLLMProvider()
