from fastapi import APIRouter, Depends
from app.schemas.profile import UserProfileResponse, UserProfileUpdateRequest
from app.services.user_service import UserService, user_service
from app.core.security import CurrentUser, get_current_user

router = APIRouter(prefix="/profile", tags=["Profile"])


@router.get("", response_model=UserProfileResponse, summary="Get Learner Profile")
async def get_profile(
    current_user: CurrentUser = Depends(get_current_user),
    service: UserService = Depends(lambda: user_service),
):
    """
    Returns the authenticated user's profile.
    Extracts identity strictly from verified Supabase JWT claims, ensuring no spoofing.
    """
    return await service.get_or_create_profile(user_id=current_user.user_id, email=current_user.email)


@router.patch("", response_model=UserProfileResponse, summary="Update Learner Profile")
async def update_profile(
    request: UserProfileUpdateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: UserService = Depends(lambda: user_service),
):
    """Updates the authenticated user's profile details."""
    return await service.update_profile(user_id=current_user.user_id, update_data=request)
