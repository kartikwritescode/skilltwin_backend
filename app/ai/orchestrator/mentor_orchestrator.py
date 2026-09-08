from typing import List, Optional, Dict, Any
from app.ai.providers.base import LLMProvider
from app.ai.schemas.ai_schemas import (
    GeneratedJourneyPlan,
    MentorRecommendationOutput,
    MentorChatAIOutput,
)
from app.ai.prompts.templates import (
    GOAL_JOURNEY_BREAKDOWN_PROMPT,
    MENTOR_SYSTEM_PROMPT,
)
from app.ai.orchestrator.context_builder import MentorContext
from app.domain.mentor.models import ActionType, ActionRecommendation
from app.core.logging import logger


class MentorOrchestrator:
    """
    Coordinates learner context, curriculum generation, and mentor decisions
    using the decoupled LLMProvider.
    Ensures that LLM outputs are strictly validated into Pydantic models.
    """

    def __init__(self, llm_provider: LLMProvider):
        self.llm_provider = llm_provider

    async def generate_journey_plan(
        self,
        goal_title: str,
        goal_description: Optional[str],
        current_level: str,
        daily_minutes: int,
        target_benchmark: Optional[str],
    ) -> GeneratedJourneyPlan:
        logger.info(f"Orchestrating journey generation for goal: '{goal_title}'")
        prompt = GOAL_JOURNEY_BREAKDOWN_PROMPT.format(
            goal_title=goal_title,
            goal_description=goal_description or "General mastery",
            current_level=current_level,
            daily_minutes=daily_minutes,
            target_benchmark=target_benchmark or "Solid practical competence",
        )

        plan = await self.llm_provider.generate_structured(
            prompt=prompt,
            response_schema=GeneratedJourneyPlan,
            system_prompt="You are an expert curriculum and pedagogy architect.",
        )
        return plan

    async def synthesize_recommendation(
        self,
        context: MentorContext,
        rule_hint: ActionType,
    ) -> MentorRecommendationOutput:
        """
        Synthesizes an empathetic, context-aware action recommendation.
        Takes the deterministic rule hint as the guiding intent.
        """
        logger.info(f"Synthesizing recommendation with intent hint: {rule_hint.value}")

        prompt = f"""
PEDAGOGICAL INTENT: {rule_hint.value}

LEARNER CONTEXT:
{context.to_llm_prompt()}

Synthesize the single next best action for this learner matching the pedagogical intent.
Provide a concise title, pedagogical reasoning ('Why this action'), estimated minutes, and confidence.
""".strip()

        recommendation = await self.llm_provider.generate_structured(
            prompt=prompt,
            response_schema=MentorRecommendationOutput,
            system_prompt=MENTOR_SYSTEM_PROMPT,
            temperature=0.2,
        )

        return recommendation

    async def generate_chat_response(
        self,
        user_message: str,
        user_id: str,
        context: Optional[MentorContext] = None,
    ) -> Dict[str, Any]:
        logger.info(f"Orchestrating mentor chat reply for user {user_id}")

        # 1. Deterministic Input Guardrail Check (Zero LLM Token Cost)
        from app.ai.guardrails.input_guardrails import input_guardrail

        goal_title = context.goal_title if context else None
        node_title = context.current_node_title if context else None
        guardrail_result = input_guardrail.validate(
            user_message=user_message,
            active_goal_title=goal_title,
            current_topic_title=node_title,
        )

        topic_label = node_title or "Current Milestone"
        action_time = context.daily_minutes if context else 20

        if not guardrail_result.is_safe:
            logger.warning(
                f"Input guardrail intercepted message for user {user_id}: "
                f"reason={guardrail_result.rejection_reason}"
            )
            return {
                "reply": guardrail_result.redirected_response,
                "is_ai_generated": False,
                "warning_message": "Pedagogical safety guardrail applied.",
                "suggested_actions": [
                    ActionRecommendation(
                        action_type=ActionType.LEARN,
                        title=f"Continue: {topic_label}",
                        reason="Maintains focus on your verified curriculum path.",
                        estimated_minutes=action_time,
                        quick_action_label="Resume",
                    )
                ],
            }

        # 2. Compact RAG context dossier (<120 tokens)
        rag_context = context.to_rag_dossier() if context else "[LEARNER RAG DOSSIER]\nNo active goal context available."
        prompt = f"""
<LEARNER_CONTEXT>
{rag_context}
</LEARNER_CONTEXT>

<USER_QUERY>
{guardrail_result.sanitized_input}
</USER_QUERY>

Respond strictly as the SkillTwin personal mentor. Concise, empathetic, and actionable. Ground all explanations in the learner's active topic, current mastery level, and known cognitive gaps.
""".strip()

        reply_text = await self.llm_provider.generate_text(
            prompt=prompt,
            system_prompt=MENTOR_SYSTEM_PROMPT,
            temperature=0.7,
        )

        # Detect provider health and quota fallback status
        is_ai = True
        warning_msg: Optional[str] = None
        provider_name = getattr(self.llm_provider, "provider_name", "mock")

        last_status = getattr(self.llm_provider, "last_status", "active")
        last_error = getattr(self.llm_provider, "last_error_detail", None)

        if "mock" in provider_name.lower():
            is_ai = False
            warning_msg = "Running offline pedagogical intelligence engine."
        elif last_status == "quota_exhausted":
            is_ai = False
            warning_msg = "Google Gemini Free Tier quota reached (429). Using offline pedagogical mentor engine."
        elif last_status != "active":
            is_ai = False
            warning_msg = last_error or f"AI Provider operating in offline fallback mode ({last_status})."

        return {
            "reply": reply_text,
            "is_ai_generated": is_ai,
            "warning_message": warning_msg,
            "suggested_actions": [
                ActionRecommendation(
                    action_type=ActionType.LEARN,
                    title=f"Continue: {topic_label}",
                    reason=f"Solidifies your understanding of {topic_label}.",
                    estimated_minutes=action_time,
                    quick_action_label="Resume",
                )
            ],
        }
