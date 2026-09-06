from typing import Optional, Dict, Any
from app.ai.providers.base import LLMProvider
from app.ai.schemas.ai_schemas import EvaluationResult
from app.ai.prompts.templates import SESSION_EVALUATION_RUBRIC
from app.core.logging import logger


class SessionEvaluator:
    """Evaluates learner responses against rubrics using the LLMProvider abstraction."""

    def __init__(self, llm_provider: LLMProvider):
        self.llm_provider = llm_provider

    async def evaluate_submission(
        self,
        concept_name: str,
        session_type: str,
        user_submission: Optional[str],
        quiz_data: Optional[Dict[str, Any]] = None,
    ) -> EvaluationResult:
        logger.info(f"Evaluating session for concept: '{concept_name}', type: '{session_type}'")

        if not user_submission and not quiz_data:
            return EvaluationResult(
                score=70.0,
                reasoning_score=70.0,
                transfer_score=70.0,
                feedback="Session recorded. Active participation logged.",
                misconceptions_detected=[],
                mastery_delta=5.0,
                confidence_delta=4.0,
            )

        prompt = SESSION_EVALUATION_RUBRIC.format(
            submission=user_submission or "Automated quiz completion.",
            concept_name=concept_name,
            session_type=session_type,
        )

        evaluation = await self.llm_provider.generate_structured(
            prompt=prompt,
            response_schema=EvaluationResult,
            system_prompt="You are a rigorous pedagogical evaluator. Assess evidence accurately without grade inflation."
        )

        return evaluation
