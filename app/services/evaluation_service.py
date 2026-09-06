from typing import Optional, List, Dict, Any
from app.ai.providers.base import LLMProvider
from app.ai.providers.factory import get_llm_provider
from app.ai.schemas.ai_schemas import EvaluationResult, TeachEvaluationAIOutput
from app.ai.prompts.templates import SESSION_EVALUATION_RUBRIC, TEACH_BACK_EVALUATION_RUBRIC
from app.core.logging import logger


class EvaluationService:
    """
    AI-driven pedagogical evaluation service. Assesses learner submissions against
    a 5point rubric: Accuracy, Reasoning, Transfer, Misconceptions, and Resolved.
    """

    def __init__(self, llm_provider: Optional[LLMProvider] = None):
        self.llm_provider = llm_provider or get_llm_provider()

    async def evaluate_submission(
        self,
        concept_name: str,
        session_type: str,
        user_submission: Optional[str],
        prior_misconceptions: Optional[List[str]] = None,
        quiz_data: Optional[Dict[str, Any]] = None,
    ) -> EvaluationResult:
        logger.info(f"Evaluating submission for {concept_name} (type='{session_type}')")

        if not user_submission and not quiz_data:
            return EvaluationResult(
                score=70.0,
                reasoning_score=70.0,
                transfer_score=70.0,
                feedback="Active participation logged.",
                misconceptions_detected=[],
                resolved_misconceptions=[],
                mastery_delta=5.0,
                confidence_delta=4.0,
            )

        prompt = SESSION_EVALUATION_RUBRIC.format(
            submission=user_submission or 'Automated session answers submitted.',
            concept_name=concept_name,
            session_type=session_type,
            prior_misconceptions=', '.join(prior_misconceptions) if prior_misconceptions else 'None',
        )

        evaluation = await self.llm_provider.generate_structured(
            prompt=prompt,
            response_schema=EvaluationResult,
            system_prompt='You are a rigorous pedagogical evaluator.',
        )
        return evaluation

    async def evaluate_teaching_explanation(
        self,
        concept_name: str,
        concept_description: str,
        prerequisites: List[str],
        explanation: str,
        mastery_score: float = 0.0,
        prior_misconceptions: Optional[List[str]] = None,
        goal_title: str = "Mastery",
    ) -> TeachEvaluationAIOutput:
        """
        Rigorous pedagogical evaluation of a learner's teach-back explanation
        against conceptual accuracy, completeness, reasoning depth, confidence, and transfer.
        """
        logger.info(f"Evaluating teach-back explanation for '{concept_name}' (len={len(explanation)})")

        prompt = TEACH_BACK_EVALUATION_RUBRIC.format(
            concept_name=concept_name,
            concept_description=concept_description,
            prerequisites=", ".join(prerequisites) if prerequisites else "None",
            mastery_score=round(mastery_score, 1),
            prior_misconceptions=", ".join(prior_misconceptions) if prior_misconceptions else "None",
            goal_title=goal_title,
            explanation=explanation.strip(),
        )

        evaluation: TeachEvaluationAIOutput = await self.llm_provider.generate_structured(
            prompt=prompt,
            response_schema=TeachEvaluationAIOutput,
            system_prompt="You are SkillTwin's rigorous pedagogical evaluator specialized in the Feynman teach-back technique.",
        )

        # Enforce validation bounds
        evaluation.conceptual_accuracy = max(0, min(100, int(evaluation.conceptual_accuracy)))
        evaluation.completeness = max(0, min(100, int(evaluation.completeness)))
        evaluation.reasoning = max(0, min(100, int(evaluation.reasoning)))
        evaluation.confidence = max(0, min(100, int(evaluation.confidence)))
        evaluation.transfer = max(0, min(100, int(evaluation.transfer)))

        valid_recommendations = {"LEARN", "REVISE", "PRACTICE", "PROVE", "TEACH", "REMEDIATE", "SKIP", "REFLECT"}
        rec_upper = evaluation.recommendation.upper()
        evaluation.recommendation = rec_upper if rec_upper in valid_recommendations else "PRACTICE"

        return evaluation


evaluation_service = EvaluationService()
