from fastapi import APIRouter, Depends, status
from app.schemas.mentor import (
    MentorTodayResponse,
    MentorMessageRequest,
    MentorMessageResponse,
)
from app.services.mentor_service import MentorService, mentor_service
from app.core.security import CurrentUser, get_current_user

router = APIRouter(prefix="/mentor", tags=["Mentor"])


@router.get("/today", response_model=MentorTodayResponse, summary="Get Today's Recommended Best Action")
async def get_mentor_today(
    current_user: CurrentUser = Depends(get_current_user),
    service: MentorService = Depends(lambda: mentor_service),
):
    """
    SkillTwin North Star: Returns what the learner should do right now,
    the pedagogical reasoning ('Why this action'), daily checklist, and mentor briefing.
    """
    return await service.get_today_brief(user_id=current_user.user_id)


@router.post("/message", response_model=MentorMessageResponse, status_code=status.HTTP_200_OK, summary="Send Message to AI Mentor")
async def send_mentor_message(
    request: MentorMessageRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: MentorService = Depends(lambda: mentor_service),
):
    """
    Send an empathetic, goal-aligned query to the persistent AI mentor.
    Receives contextual guidance and actionable next step recommendations.
    """
    return await service.send_message(user_id=current_user.user_id, request=request)
