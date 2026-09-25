import re
from typing import Optional, List, Dict, Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.core.database import get_session_factory
from app.core.db_models import MicroSubgraphModel
from app.schemas.adaptive_path import SynthesizedSubgraphSchema, SynthesizedConceptItem
from app.ai.providers.base import LLMProvider
from app.ai.providers.factory import get_llm_provider
from app.services.adag_assembler import adag_assembler, CyclicDependencyError


class NovelSubgraphSynthesizer:
    """
    Tier 3 Novel Subgraph Synthesis & Global Deduplication Engine.
    When a learner inputs a niche topic not covered by canonical ontologies,
    this service synthesizes only the missing 3-to-5 node micro-subgraph schema
    via a token-budgeted LLM micro-prompt (<350 tokens) and publishes it
    to the global database for perpetual 0-token reuse.
    """

    def __init__(self, llm_provider: Optional[LLMProvider] = None):
        self._llm_provider = llm_provider

    @property
    def llm_provider(self) -> LLMProvider:
        if self._llm_provider is None:
            self._llm_provider = get_llm_provider()
        return self._llm_provider

    def slugify(self, text: str) -> str:
        """Converts arbitrary query text into a standardized kebab-case slug."""
        text = text.lower().strip()
        text = re.sub(r"[^\w\s-]", "", text)
        return re.sub(r"[\s_]+", "-", text).strip("-")[:50]

    async def synthesize_micro_subgraph(
        self,
        topic_query: str,
        target_level: str = "intermediate",
        session: Optional[AsyncSession] = None,
    ) -> MicroSubgraphModel:
        """
        Synthesizes a novel micro-subgraph schema if absent, or returns
        the globally cached instance at 0 tokens if already present.
        """
        if session is None:
            session_factory = get_session_factory()
            async with session_factory() as sess:
                return await self.synthesize_micro_subgraph(topic_query, target_level, sess)

        expected_slug = self.slugify(topic_query)

        # Step 1: Check Database Cache for Global Deduplication (0 Tokens)
        stmt = select(MicroSubgraphModel).where(MicroSubgraphModel.slug == expected_slug)
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            logger.info(
                f"[NovelSubgraphSynthesizer] 100% Global Cache Hit for '{expected_slug}'. "
                f"Returning existing micro-subgraph (0 tokens consumed)."
            )
            return existing

        # Step 2: Construct Hyper-Compact, Schema-Enforced LLM Micro-Prompt
        logger.info(
            f"[NovelSubgraphSynthesizer] Cache miss for niche topic '{topic_query}'. "
            f"Invoking Gemini Flash micro-synthesis (<350 tokens)..."
        )

        prompt = (
            f'Synthesize a modular, self-contained micro-subgraph curriculum for:\n'
            f'Topic: "{topic_query}"\n'
            f'Target Level: "{target_level}"\n\n'
            f'Rules:\n'
            f'1. Output 3 to 5 milestone concepts forming a strict Directed Acyclic Graph (DAG).\n'
            f'2. Assign slug="{expected_slug}" in kebab-case.\n'
            f'3. Estimated duration between 30 and 180 total minutes.\n'
            f'4. Enforce strict acyclicity (no concept may depend on itself or a downstream concept).'
        )

        system_prompt = (
            "You are a Curriculum Architect and Optimization Engineer. "
            "Generate concise, structurally validated technical learning subgraphs. "
            "Output strictly valid JSON matching the schema."
        )

        synthesized_data: SynthesizedSubgraphSchema = await self.llm_provider.generate_structured(
            response_schema=SynthesizedSubgraphSchema,
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=0.2,
            max_tokens=400,
        )

        # Step 3: Validate Acyclicity of Generated Concepts
        concept_nodes = [{"id": c.concept_id} for c in synthesized_data.concepts]
        concept_ids = {c.concept_id for c in synthesized_data.concepts}
        raw_concept_edges: List[Tuple[str, str]] = []

        for c in synthesized_data.concepts:
            for p in c.prerequisites:
                if p in concept_ids and p != c.concept_id:
                    raw_concept_edges.append((p, c.concept_id))

        try:
            # Verify acyclicity
            adag_assembler.verify_and_sort_dag(concept_nodes, raw_concept_edges)
        except CyclicDependencyError:
            logger.warning(
                f"[NovelSubgraphSynthesizer] Cycle detected in LLM synthesized concepts for '{topic_query}'. "
                f"Auto-repairing graph into strict forward chain."
            )
            # Auto-repair by enforcing sequential forward chain based on declaration order
            for idx, c in enumerate(synthesized_data.concepts):
                c.prerequisites = [synthesized_data.concepts[idx - 1].concept_id] if idx > 0 else []

        # Step 4: Persist to Global Database for Deduplication
        final_slug = self.slugify(synthesized_data.slug or expected_slug)
        subgraph_id = f"subgraph_{final_slug}"

        # Check again in case existing by final_slug
        existing_final = await session.execute(
            select(MicroSubgraphModel).where(
                (MicroSubgraphModel.slug == final_slug) | (MicroSubgraphModel.id == subgraph_id)
            )
        )
        already_present = existing_final.scalar_one_or_none()
        if already_present:
            return already_present

        total_minutes = sum(c.estimated_minutes for c in synthesized_data.concepts)
        total_minutes = max(30, min(total_minutes, 360))

        # If novel subgraph has no external prerequisites, it serves as the foundational root for this domain
        tier = synthesized_data.tier
        if not synthesized_data.prerequisites and tier != "foundational":
            tier = "foundational"

        new_subgraph = MicroSubgraphModel(
            id=subgraph_id,
            ontology_id=None,  # Independent / novel subgraph
            slug=final_slug,
            title=synthesized_data.title or topic_query,
            tier=tier,
            estimated_minutes=total_minutes,
            prerequisites=synthesized_data.prerequisites,
        )

        session.add(new_subgraph)
        await session.commit()
        await session.refresh(new_subgraph)

        logger.info(
            f"[NovelSubgraphSynthesizer] Successfully synthesized and indexed novel subgraph "
            f"'{new_subgraph.slug}' ({len(synthesized_data.concepts)} concepts). Now permanently 0-tokens."
        )

        return new_subgraph


novel_subgraph_synthesizer = NovelSubgraphSynthesizer()
