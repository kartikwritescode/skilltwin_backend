from typing import Optional, List, Dict, Any
from app.ai.providers.base import LLMProvider
from app.ai.providers.factory import get_llm_provider
from app.ai.schemas.ai_schemas import EvaluationResult, TeachEvaluationAIOutput, StepEvaluation
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
        steps: Optional[List[Any]] = None,
    ) -> EvaluationResult:
        logger.info(f"Evaluating submission for {concept_name} (type='{session_type}')")

        # Check if submission contains any actual answers
        has_answers = False
        if user_submission and user_submission.strip():
            has_answers = True
        if quiz_data:
            for item in quiz_data.get("step_responses", []):
                resp = item.get("response") or item.get("answer")
                if resp is not None and str(resp).strip():
                    has_answers = True
                    break
            for item in quiz_data.get("quiz_results", []):
                if item:
                    has_answers = True
                    break

        # If user provided NO answers:
        if not has_answers:
            step_evals = []
            if steps:
                for s in steps:
                    step_evals.append(
                        StepEvaluation(
                            step_id=getattr(s, "id", ""),
                            question=getattr(s, "prompt", "") or getattr(s, "instruction", "") or getattr(s, "title", ""),
                            user_answer="[Unanswered]",
                            is_correct=False,
                            correct_answer=getattr(s, "correct_answer", "") or "Please review the concept material.",
                            explanation=getattr(s, "explanation", "") or "No answer provided. Active retrieval is required for verifiable mastery.",
                        )
                    )
            return EvaluationResult(
                score=0.0,
                reasoning_score=0.0,
                transfer_score=0.0,
                accuracy_score=0.0,
                completeness_score=0.0,
                feedback=f"No answers were submitted for {concept_name}. Review the concept material and attempt the questions to build verifiable mastery.",
                improvements=[],
                focus_areas=[f"Attempt active practice for {concept_name}", "Review foundational invariants"],
                misconceptions_detected=[],
                resolved_misconceptions=[],
                mastery_delta=0.0,
                confidence_delta=-5.0,
                step_evaluations=step_evals,
            )

        # Build formatted steps context for LLM
        steps_context_lines = []
        if steps:
            for s in steps:
                s_id = getattr(s, "id", "")
                s_prompt = getattr(s, "prompt", "") or getattr(s, "instruction", "")
                s_opts = getattr(s, "options", [])
                s_corr = getattr(s, "correct_answer", "")
                s_rubric = getattr(s, "rubric_criteria", "")

                user_ans = "[Unanswered]"
                if quiz_data:
                    for r in quiz_data.get("step_responses", []):
                        if r.get("step_id") == s_id or str(r.get("step_order")) == str(getattr(s, "order", -1)):
                            ans = str(r.get("response") or r.get("answer") or "").strip()
                            if ans:
                                user_ans = ans
                            break

                steps_context_lines.append(
                    f"- Step ID: {s_id} | Title: {getattr(s, 'title', '')}\n"
                    f"  Prompt: {s_prompt}\n"
                    f"  Options: {', '.join(s_opts) if s_opts else 'N/A'}\n"
                    f"  Authoritative Correct Answer: {s_corr or 'N/A'}\n"
                    f"  Rubric: {s_rubric or 'N/A'}\n"
                    f"  Learner Answer: {user_ans}\n"
                )

        steps_context_str = "\n".join(steps_context_lines) if steps_context_lines else "None provided."

        prompt = SESSION_EVALUATION_RUBRIC.format(
            submission=user_submission or "Step-by-step answers provided in session context.",
            steps_context=steps_context_str,
            concept_name=concept_name,
            session_type=session_type,
            prior_misconceptions=", ".join(prior_misconceptions) if prior_misconceptions else "None",
        )

        evaluation = await self.llm_provider.generate_structured(
            prompt=prompt,
            response_schema=EvaluationResult,
            system_prompt="You are SkillTwin's rigorous pedagogical evaluator. Compare each answer strictly against the correct answer and rubric.",
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
