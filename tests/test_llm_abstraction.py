import pytest
from app.ai.providers.factory import get_llm_provider
from app.ai.providers.base import LLMProvider
from app.ai.schemas.ai_schemas import GeneratedJourneyPlan


@pytest.mark.asyncio
async def test_llm_provider_methods():
    provider: LLMProvider = get_llm_provider()

    # 1. generate_text()
    text = await provider.generate_text("Explain binary search simply.")
    assert isinstance(text, str)
    assert len(text) > 10

    # 2. generate_structured()
    structured = await provider.generate_structured(
        prompt="Flutter Masterclass",
        response_schema=GeneratedJourneyPlan
    )
    assert isinstance(structured, GeneratedJourneyPlan)
    assert len(structured.nodes) > 0

    # 3. embed()
    embeddings = await provider.embed(["Sample document chunk for pgvector indexing."])
    assert isinstance(embeddings, list)
    assert len(embeddings) == 1
    assert len(embeddings[0]) == 1536  # Standard embedding dimension

    # 4. evaluate()
    eval_output = await provider.evaluate(
        rubric="Pedagogical accuracy",
        target_content="An event loop continuously polls the microtask and event queues to dispatch callbacks."
    )
    assert isinstance(eval_output, dict)
    assert "score" in eval_output
    assert "feedback" in eval_output
    assert eval_output["score"] >= 0.0
