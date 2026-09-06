from fastapi import APIRouter, Depends, status
from app.schemas.revision import (
    RevisionNextResponse,
    ReviewItemResponse,
    ReviewCompleteRequest,
    ReviewSubmissionRequest,
    MentorNotificationsResponse,
)
from app.services.revision_service import RevisionService, revision_service
from app.core.security import CurrentUser, get_current_user

router = APIRouter(prefix="/revision", tags=["Revision"])


@router.get("/next", response_model=RevisionNextResponse, summary="Get Next Retrieval Practice Queue")
async def get_next_revision(
    current_user: CurrentUser = Depends(get_current_user),
    service: RevisionService = Depends(lambda: revision_service),
):
    """
    Returns prioritized 3-10 minute retrieval practice items based on retention decay,
    misconceptions, and spaced repetition intervals.
    """
    return await service.get_next_retrieval(user_id=current_user.user_id)


@router.post("/{id}/complete", response_model=ReviewItemResponse, status_code=status.HTTP_200_OK, summary="Complete Spaced Review")
async def complete_spaced_review(
    id: str,
    request: ReviewCompleteRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: RevisionService = Depends(lambda: revision_service),
):
    """
    Completes a spaced retrieval review session.
    Applies RetentionEngine:
    - Gradually reduces review frequency (expands interval) on successful retrieval.
    - Contracts interval on failure.
    - Recalibrates next_review, retention_score, and composite priority.
    """
    return await service.complete_review(user_id=current_user.user_id, review_id=id, request=request)


@router.post("/submit", response_model=ReviewItemResponse, status_code=status.HTTP_200_OK, summary="Submit Retrieval Result")
async def submit_retrieval_review(
    request: ReviewSubmissionRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: RevisionService = Depends(lambda: revision_service),
):
    """Submits spaced retrieval practice result and reschedules interval (backwards compatible)."""
    return await service.submit_retrieval(user_id=current_user.user_id, submission=request)


@router.get("/notifications", response_model=MentorNotificationsResponse, summary="Get Mentor Revision Notifications")
async def get_revision_notifications(
    current_user: CurrentUser = Depends(get_current_user),
    service: RevisionService = Depends(lambda: revision_service),
):
    """Returns active mentor notifications reminding the learner of decaying retention cards."""
    return await service.get_mentor_notifications(user_id=current_user.user_id)
