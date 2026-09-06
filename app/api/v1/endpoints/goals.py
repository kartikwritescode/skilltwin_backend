from typing import List
from fastapi import APIRouter, Depends, status
from app.schemas.goals import GoalCreateRequest, GoalUpdateRequest, GoalResponse
from app.services.goal_service import GoalService, goal_service
from app.core.security import CurrentUser, get_current_user

router = APIRouter(prefix="/goals", tags=["Goals"])


@router.post("", response_model=GoalResponse, status_code=status.HTTP_201_CREATED, summary="Create Goal & Initialize Journey Generation")
async def create_goal(
    request: GoalCreateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: GoalService = Depends(lambda: goal_service),
):
    """
    Creates a new learning goal for the authenticated learner.
    Initializes an adaptive journey in PENDING/PROCESSING state and triggers asynchronous
    background roadmap generation, returning the goal and tracking status immediately.
    """
    return await service.create_goal(user_id=current_user.user_id, request=request)


@router.get("", response_model=List[GoalResponse], summary="List Authenticated Learner Goals")
async def list_goals(
    current_user: CurrentUser = Depends(get_current_user),
    service: GoalService = Depends(lambda: goal_service),
):
    """List all learning goals owned by the authenticated learner."""
    return await service.list_goals_for_user(user_id=current_user.user_id)


@router.get("/{goal_id}", response_model=GoalResponse, summary="Get Goal by ID")
async def get_goal(
    goal_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    service: GoalService = Depends(lambda: goal_service),
):
    """
    Retrieve goal details and live journey generation status.
    Strictly verifies ownership against the authenticated JWT identity.
    """
    return await service.get_goal(user_id=current_user.user_id, goal_id=goal_id)


@router.patch("/{goal_id}", response_model=GoalResponse, summary="Partially Update Goal")
async def patch_goal(
    goal_id: str,
    request: GoalUpdateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: GoalService = Depends(lambda: goal_service),
):
    """
    Partially update properties of an existing goal (e.g. daily minutes, target deadline, constraints).
    Strictly verifies ownership against the authenticated JWT identity.
    """
    return await service.patch_goal(user_id=current_user.user_id, goal_id=goal_id, request=request)
