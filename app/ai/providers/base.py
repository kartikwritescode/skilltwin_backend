from abc import ABC, abstractmethod
from typing import TypeVar, Type, Optional, List, Dict, Any
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMProvider(ABC):
    """
    Vendor-neutral abstraction layer for Large Language Models.
    SkillTwin business logic NEVER calls OpenAI, Gemini, Anthropic, or Ollama directly.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Returns the unique identifier of the provider."""
        pass

    @abstractmethod
    async def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        **kwargs
    ) -> str:
        """Generate unstructured text from a prompt."""
        pass

    @abstractmethod
    async def generate_structured(
        self,
        prompt: str,
        response_schema: Type[T],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        **kwargs
    ) -> T:
        """Generate validated Pydantic model response from a prompt."""
        pass

    @abstractmethod
    async def embed(
        self,
        texts: List[str],
        **kwargs
    ) -> List[List[float]]:
        """Generate vector embeddings for a list of input texts."""
        pass

    @abstractmethod
    async def evaluate(
        self,
        rubric: str,
        target_content: str,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Evaluate target learner content (e.g. proof of work, quiz answer, explanation)
        against a structured pedagogical rubric.
        """
        pass
