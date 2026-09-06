import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from app.repositories.mentor_repository import MentorRepository, mentor_repository
from app.domain.mentor.models import MentorMessage, MentorRole
from app.schemas.mentor import (
    MentorTodayResponse,
    MentorMessageRequest,
    MentorMessageResponse,
    ActionRecommendationSchema,
)
from app.services.recommendation_service import RecommendationService, recommendation_service
from app.ai.orchestrator.context_builder import MentorContextBuilder, context_builder
from app.ai.orchestrator.mentor_orchestrator import MentorOrchestrator
from app.ai.providers.factory import get_llm_provider
from app.core.logging import logger


class MentorService:
    def __init__(
        self,
        mentor_repo: MentorRepository = mentor_repository,
        rec_service: RecommendationService = recommendation_service,
        ctx_builder: MentorContextBuilder = context_builder,
        orchestrator: Optional[MentorOrchestrator] = None,
    ):
        self.mentor_repo = mentor_repo
        self.rec_service = rec_service
        self.ctx_builder = ctx_builder
        self.orchestrator = orchestrator or MentorOrchestrator(get_llm_provider())

    async def get_today_brief(self, user_id: str) -> MentorTodayResponse:
        """Returns the deterministic-first, LLM-calibrated next best action."""
        return await self.rec_service.get_today_recommendation(user_id)

    async def send_message(self, user_id: str, request: MentorMessageRequest) -> MentorMessageResponse:
        logger.info(f"Processing message from user {user_id}: '{request.message[:60]}...'")

        # 1. Persist learner message
        user_msg = MentorMessage(
            id=f"msg_{uuid.uuid4().hex[:10]}",
            user_id=user_id,
            role=MentorRole.USER,
            content=request.message,
            metadata=request.context or {},
        )
        await self.mentor_repo.save(user_msg)

        # 2. Build selective context
        context = await self.ctx_builder.build_context(user_id)

        # 3. Generate contextual mentor reply via Orchestrator
        ai_result = await self.orchestrator.generate_chat_response(
            user_message=request.message,
            user_id=user_id,
            context=context,
        )

        # 4. Persist mentor reply
        mentor_msg = MentorMessage(
            id=f"msg_{uuid.uuid4().hex[:10]}",
            user_id=user_id,
            role=MentorRole.MENTOR,
            content=ai_result["reply"],
            metadata={"in_reply_to": user_msg.id},
        )
        await self.mentor_repo.save(mentor_msg)

        suggested_schemas = [
            ActionRecommendationSchema(
                action_type=a.action_type,
                title=a.title,
                reason=a.reason,
                estimated_minutes=a.estimated_minutes,
                quick_action_label=a.quick_action_label,
            )
            for a in ai_result.get("suggested_actions", [])
        ]

        return MentorMessageResponse(
            id=mentor_msg.id,
            role=MentorRole.MENTOR,
            content=mentor_msg.content,
            suggested_actions=suggested_schemas,
            created_at=mentor_msg.created_at,
            is_ai_generated=ai_result.get("is_ai_generated", True),
            warning_message=ai_result.get("warning_message"),
        )


mentor_service = MentorService()
