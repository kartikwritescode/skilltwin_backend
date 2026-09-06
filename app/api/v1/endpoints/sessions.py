from fastapi import APIRouter, Depends, status
from app.schemas.sessions import (
    SessionCreateRequest,
    SessionCompleteRequest,
    SessionResponse,
)
from app.services.session_service import SessionService, session_service
from app.core.security import CurrentUser, get_current_user

router = APIRouter(prefix="/sessions", tags=["Sessions"])


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED, summary="Start Learning / Practice Session")
async def start_session(
    request: SessionCreateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: SessionService = Depends(lambda: session_service),
):
    """Initiates an interactive learning, practice, proof, or teach-back session."""
    return await service.create_session(user_id=current_user.user_id, request=request)


@router.post("/{session_id}/complete", response_model=SessionResponse, status_code=status.HTTP_200_OK, summary="Complete Session & Evaluate Evidence")
async def complete_session(
    session_id: str,
    request: SessionCompleteRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: SessionService = Depends(lambda: session_service),
):
    """
    Submits user proof/answers, invokes the AI evaluation rubric,
    persists evidence, and updates learner twin mastery state.
    """
    return await service.complete_session(
        user_id=current_user.user_id, session_id=session_id, request=request
    )
