import pytest
import time
from unittest.mock import patch, MagicMock
from httpx import AsyncClient
from app.ai.providers.factory import get_llm_provider
from app.services.twin_analytics_service import twin_analytics_service
try:
    from tests.test_dynamic_learning_system import ensure_active_path
except ImportError:
    from test_dynamic_learning_system import ensure_active_path


@pytest.mark.asyncio
async def test_trace_twin_dashboard_request(async_client: AsyncClient, auth_headers):
    # Ensure user has active roadmap and some completed progress
    await ensure_active_path(async_client, auth_headers)

    llm = get_llm_provider()
    # Spy on LLM provider methods
    llm_calls = []
    original_generate = getattr(llm, "generate", None)
    original_generate_structured = getattr(llm, "generate_structured", None)

    async def spy_generate(*args, **kwargs):
        llm_calls.append(("generate", args, kwargs))
        if original_generate:
            return await original_generate(*args, **kwargs)
        return ""

    async def spy_generate_structured(*args, **kwargs):
        llm_calls.append(("generate_structured", args, kwargs))
        if original_generate_structured:
            return await original_generate_structured(*args, **kwargs)
        return {}

    with patch.object(llm, "generate", side_effect=spy_generate) if hasattr(llm, "generate") else patch.object(llm, "generate_text", side_effect=spy_generate, create=True):
        t_net_start = time.perf_counter()
        response = await async_client.get("/api/v1/twin/dashboard", headers=auth_headers)
        t_net_end = time.perf_counter()

    assert response.status_code == 200
    data = response.json()
    total_latency_ms = (t_net_end - t_net_start) * 1000

    print("\n--- TWIN AUDIT TRACE RESULTS ---")
    print(f"Total /twin/dashboard endpoint latency: {total_latency_ms:.2f}ms")
    print(f"Total LLM calls made during GET /twin/dashboard: {len(llm_calls)}")
    print(f"has_sufficient_data: {data.get('has_sufficient_data')}")
    print(f"overall_mastery: {data.get('overall_mastery')}")
    print(f"verified_evidence_count: {data.get('verified_evidence_count')}")

    # Check whether LLM is called
    assert len(llm_calls) == 0, "GET /twin/dashboard MUST NOT trigger any LLM call!"
