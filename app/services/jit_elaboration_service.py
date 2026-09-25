import asyncio
from typing import Optional, List, Dict, Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import logger
from app.core.database import get_session_factory
from app.core.db_models import PathNodeModel, ElaboratedTopicCacheModel
from app.schemas.adaptive_path import ElaboratedTopicContent
from app.ai.providers.base import LLMProvider
from app.ai.providers.factory import get_llm_provider


class JITElaborationService:
    """
    Just-In-Time (JIT) Progressive Elaboration Engine.
    Defers expensive lesson, quiz, and challenge generation until the learner
    is within the horizon window (distance <= 2 milestones).
    Checks the global shared cache before calling AI providers, eliminating 70%+ token waste.
    """

    def __init__(self, llm_provider: Optional[LLMProvider] = None):
        self._llm_provider = llm_provider

    @property
    def llm_provider(self) -> LLMProvider:
        if self._llm_provider is None:
            self._llm_provider = get_llm_provider()
        return self._llm_provider

    async def check_and_elaborate_horizon(
        self,
        path_id: str,
        current_node_order: int,
        horizon: int = 2,
        session: Optional[AsyncSession] = None,
    ) -> List[PathNodeModel]:
        """
        Inspects upcoming nodes within the horizon window [current_node_order + 1, current_node_order + horizon].
        Elaborates any node whose is_elaborated flag is False.
        """
        if session is None:
            session_factory = get_session_factory()
            async with session_factory() as sess:
                return await self.check_and_elaborate_horizon(
                    path_id, current_node_order, horizon, sess
                )

        stmt = (
            select(PathNodeModel)
            .where(
                PathNodeModel.path_id == path_id,
                PathNodeModel.order_index > current_node_order,
                PathNodeModel.order_index <= current_node_order + horizon,
                PathNodeModel.is_elaborated == False,  # noqa: E712
            )
            .order_by(PathNodeModel.order_index)
        )
        result = await session.execute(stmt)
        horizon_nodes = list(result.scalars().all())

        if not horizon_nodes:
            logger.debug(
                f"[JITElaborationService] No un-elaborated nodes in horizon [{current_node_order + 1}..{current_node_order + horizon}] for path '{path_id}'"
            )
            return []

        logger.info(
            f"[JITElaborationService] Pre-warming {len(horizon_nodes)} horizon nodes for path '{path_id}'"
        )
        elaborated_nodes: List[PathNodeModel] = []

        for node in horizon_nodes:
            await self.elaborate_node_content(node, session)
            elaborated_nodes.append(node)

        return elaborated_nodes

    async def elaborate_node_content(
        self, node: PathNodeModel, session: AsyncSession
    ) -> Dict[str, Any]:
        """
        Elaborates lesson markdown, key invariants, practice questions, and code challenges.
        First checks elaborated_topic_cache (0 tokens). If missing, calls Gemini Flash (<350 tokens)
        and populates the global cache for future reuse.
        """
        # Step 1: Global Cache Check (0 Tokens)
        stmt = select(ElaboratedTopicCacheModel).where(
            ElaboratedTopicCacheModel.concept_id == node.concept_id
        )
        result = await session.execute(stmt)
        cached_entry = result.scalar_one_or_none()

        if cached_entry:
            logger.info(
                f"[JITElaborationService] Global Cache HIT for concept '{node.concept_id}' (0 tokens consumed)."
            )
            content_dict = {
                "concept_id": cached_entry.concept_id,
                "difficulty": cached_entry.difficulty,
                "explanation_markdown": cached_entry.explanation_markdown,
                "key_invariants": cached_entry.key_invariants,
                "practice_questions": cached_entry.practice_questions,
                "code_challenges": cached_entry.code_challenges,
                "prompt_version": cached_entry.prompt_version,
            }

            node.is_elaborated = True
            current_meta = dict(node.node_metadata or {})
            current_meta["content"] = content_dict
            node.node_metadata = current_meta
            await session.commit()
            return content_dict

        # Step 2: Cache Miss - Gemini Flash Structured JIT Generation (<350 tokens)
        logger.info(
            f"[JITElaborationService] Cache MISS for concept '{node.concept_id}' (node: '{node.title}'). "
            f"Invoking Gemini Flash micro-elaboration..."
        )

        prompt = (
            f'Generate a focused technical learning capsule for:\n'
            f'concept_id: "{node.concept_id}"\n'
            f'topic title: "{node.title}"\n\n'
            f'Requirements:\n'
            f'1. explanation_markdown: 2 clear paragraphs with technical intuition and a real-world analogy.\n'
            f'2. key_invariants: Exactly 3 non-negotiable mental models or rules.\n'
            f'3. practice_questions: 2 to 3 diagnostic multiple-choice questions with answer keys and explanations.\n'
            f'4. code_challenges: 1 practical coding challenge with starter_code, solution_code, and test cases.\n'
            f'Budget: Keep response ultra-concise (<350 output tokens).'
        )

        system_prompt = (
            "You are an Elite Software Architect and Pedagogical Mentor. "
            "Generate concise, high-signal educational content. "
            "Enforce strict JSON matching the schema."
        )

        content: ElaboratedTopicContent = await self.llm_provider.generate_structured(
            response_schema=ElaboratedTopicContent,
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=0.2,
            max_tokens=400,
        )

        # Step 3: Insert into Global Elaborated Cache for Perpetual Reuse
        cache_entry = ElaboratedTopicCacheModel(
            concept_id=node.concept_id,
            difficulty=content.difficulty,
            explanation_markdown=content.explanation_markdown,
            key_invariants=content.key_invariants,
            practice_questions=[q.model_dump() for q in content.practice_questions],
            code_challenges=[c.model_dump() for c in content.code_challenges],
            prompt_version=content.prompt_version,
        )
        session.add(cache_entry)

        # Step 4: Attach Content to Node and Commit
        content_dict = content.model_dump()
        node.is_elaborated = True
        current_meta = dict(node.node_metadata or {})
        current_meta["content"] = content_dict
        node.node_metadata = current_meta

        await session.commit()
        await session.refresh(node)

        logger.info(
            f"[JITElaborationService] Successfully elaborated and cached content for '{node.concept_id}'."
        )
        return content_dict

    def pre_warm_horizon_worker(
        self, path_id: str, current_node_order: int, horizon: int = 2
    ):
        """
        Spawns a detached asynchronous background worker to pre-generate horizon nodes
        without blocking the learner's immediate UI interaction.
        """
        async def _worker():
            try:
                session_factory = get_session_factory()
                async with session_factory() as session:
                    await self.check_and_elaborate_horizon(
                        path_id, current_node_order, horizon, session
                    )
            except Exception as e:
                logger.error(
                    f"[JITElaborationService] Horizon pre-warm background error for path '{path_id}': {e}",
                    exc_info=True,
                )

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_worker())
        except RuntimeError:
            # Fallback if outside event loop
            asyncio.run(_worker())

    async def on_node_completed(
        self, path_id: str, node_id: str, session: Optional[AsyncSession] = None
    ) -> Optional[PathNodeModel]:
        """
        Completion hook: marks active milestone as COMPLETED and automatically triggers
        the horizon pre-warm worker for subsequent nodes.
        """
        if session is None:
            session_factory = get_session_factory()
            async with session_factory() as sess:
                return await self.on_node_completed(path_id, node_id, sess)

        node = await session.get(PathNodeModel, node_id)
        if not node:
            return None

        node.state = "COMPLETED"
        await session.commit()
        await session.refresh(node)

        # Trigger background horizon pre-warm for the next 2 milestones
        self.pre_warm_horizon_worker(path_id, node.order_index, horizon=2)
        return node


jit_elaboration_service = JITElaborationService()
