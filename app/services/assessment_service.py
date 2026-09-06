from typing import Optional, Dict, Any, List
from app.services.evaluation_service import EvaluationService, evaluation_service
from app.ai.schemas.ai_schemas import EvaluationResult
from app.core.logging import logger


class AssessmentService:
    def __init__(self, eval_service: Optional[EvaluationService] = None):
        self.eval_service = eval_service or evaluation_service

    async def evaluate_learner_performance(
        self,
        concept_name: str,
        session_type: str,
        submission: Optional[str],
        prior_misconceptions: Optional[List[str]] = None,
        quiz_data: Optional[Dict[str, Any]] = None,
        steps: Optional[List[Any]] = None,
    ) -> EvaluationResult:
        logger.info(f"Assessing performance on '{concept_name}' ({session_type})")
        return await self.eval_service.evaluate_submission(
            concept_name=concept_name,
            session_type=session_type,
            user_submission=submission,
            prior_misconceptions=prior_misconceptions,
            quiz_data=quiz_data,
            steps=steps,
        )


assessment_service = AssessmentService()

