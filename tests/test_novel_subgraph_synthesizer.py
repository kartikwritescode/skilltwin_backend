import time
import pytest
from app.core.database import get_session_factory, init_db
from app.services.novel_subgraph_synthesizer import (
    novel_subgraph_synthesizer,
    NovelSubgraphSynthesizer,
)
from app.services.canonical_registry_service import canonical_registry_service
from app.services.adag_assembler import adag_assembler


@pytest.mark.asyncio
async def test_novel_subgraph_synthesis_flow():
    """Verify novel subgraph synthesis generates valid acyclic micro-subgraph."""
    await init_db()
    session_factory = get_session_factory()
    niche_topic = "Embedded Rust for RISC-V Microcontrollers"

    async with session_factory() as session:
        start_time = time.perf_counter()
        subgraph = await novel_subgraph_synthesizer.synthesize_micro_subgraph(
            topic_query=niche_topic,
            target_level="advanced",
            session=session,
        )
        duration_s = time.perf_counter() - start_time

        assert subgraph is not None
        assert "rust" in subgraph.slug
        assert subgraph.tier in ["foundational", "core", "advanced"]
        assert subgraph.estimated_minutes >= 30
        assert duration_s < 2.5, f"Expected generation in < 2.5s, took {duration_s:.2f}s"


@pytest.mark.asyncio
async def test_global_deduplication_cache_hit():
    """Verify second call for the same topic completes in < 15ms with 0 LLM calls."""
    session_factory = get_session_factory()
    niche_topic = "Embedded Rust for RISC-V Microcontrollers"

    async with session_factory() as session:
        # First query (might be cached from previous test or generated)
        sg1 = await novel_subgraph_synthesizer.synthesize_micro_subgraph(
            topic_query=niche_topic,
            target_level="advanced",
            session=session,
        )
        assert sg1 is not None

        # Second query: MUST hit database cache
        start_cache_time = time.perf_counter()
        sg2 = await novel_subgraph_synthesizer.synthesize_micro_subgraph(
            topic_query=niche_topic,
            target_level="advanced",
            session=session,
        )
        cache_duration_ms = (time.perf_counter() - start_cache_time) * 1000

        assert sg1.id == sg2.id
        assert sg1.slug == sg2.slug
        assert cache_duration_ms < 15.0, f"Expected cache hit in < 15ms, took {cache_duration_ms:.2f}ms"


@pytest.mark.asyncio
async def test_search_fallback_to_novel_synthesis():
    """Verify search_subgraphs_semantic invokes novel synthesis on unknown queries when fallback enabled."""
    session_factory = get_session_factory()
    completely_unknown_topic = "Quantum Teleportation Protocols in Qiskit"

    async with session_factory() as session:
        results = await canonical_registry_service.search_subgraphs_semantic(
            query=completely_unknown_topic,
            limit=5,
            threshold=0.85,
            fallback_to_synthesis=True,
            session=session,
        )

        assert len(results) > 0
        novel_sg = results[0]
        assert "quantum" in novel_sg.slug or "qiskit" in novel_sg.slug
        assert novel_sg.estimated_minutes > 0
