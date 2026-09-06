from fastapi import APIRouter, Depends
from app.schemas.learner import LearnerTwinResponse
from app.services.learner_service import LearnerService, learner_service
from app.core.security import CurrentUser, get_current_user

router = APIRouter(prefix="/twin", tags=["Learner Twin"])


@router.get("", response_model=LearnerTwinResponse, summary="Get Live Learner Twin State")
async def get_learner_twin(
    current_user: CurrentUser = Depends(get_current_user),
    service: LearnerService = Depends(lambda: learner_service),
):
    """
    Returns the comprehensive live Learner Twin state:
    - Multi-factor concept mastery scores
    - Calibrated confidence and retention scores
    - Knowledge risk rankings and active weaknesses
    - Recent verified evidence proofs
    """
    return await service.get_learner_twin(user_id=current_user.user_id)
