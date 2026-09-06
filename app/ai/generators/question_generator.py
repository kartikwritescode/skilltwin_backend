from typing import Optional, List, Dict, Any
from app.ai.providers.base import LLMProvider
from app.ai.providers.factory import get_llm_provider
from app.ai.schemas.ai_schemas import GeneratedSessionPlan
from app.ai.prompts.templates import QUESTION_GENERATION_PROMPT
from app.core.logging import logger


class QuestionGenerator:
    """
    Synthesizes structured, non-random session steps tailored to the learner's exact cognitive state.
    Inputs received:
    - goal
    - concept
    - learner level
    - known weaknesses
    - misconceptions
    - relevant resource context
    """

    def __init__(self, llm_provider: Optional[LLMProvider] = None):
        self.llm_provider = llm_provider or get_llm_provider()

    async def generate_session_plan(
        self,
        goal_title: str,
        target_benchmark: str,
        concept_name: str,
        concept_description: str,
        learner_level: str,
        known_weaknesses: List[str],
        misconceptions: List[str],
        resource_context: str,
        session_type: str,
    ) -> GeneratedSessionPlan:
        logger.info(
            f'Requesting plan for {concept_name}'
        )
        prompt = QUESTION_GENERATION_PROMPT.format(
            goal_title=goal_title or 'General Software Mastery',
            target_benchmark=target_benchmark or 'Production Readiness',
            concept_name=concept_name,
            concept_description=concept_description or 'Core framework',
            learner_level=learner_level or 'intermediate',
            known_weaknesses=', '.join(known_weaknesses) if known_weaknesses else 'None',
            misconceptions=', '.join(misconceptions) if misconceptions else 'None',
            resource_context=resource_context or 'Docs',
            session_type=session_type,
        )
        plan = await self.llm_provider.generate_structured(
            prompt=prompt,
            response_schema=GeneratedSessionPlan,
            system_prompt='You are an expert cognitive tutor.',
        )
        return plan



question_generator = QuestionGenerator()
