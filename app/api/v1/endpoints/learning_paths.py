from fastapi import APIRouter, Depends, status
from typing import Optional
from app.schemas.dynamic_learning import (
    LearningGoalCreateRequest,
    LearningGoalResponse,
    LearningPathResponse,
    HomeDashboardResponse,
    TwinDashboardResponse,
)
from app.services.learning_path_service import LearningPathService, learning_path_service
from app.services.twin_analytics_service import TwinAnalyticsService, twin_analytics_service
from app.core.security import CurrentUser, get_current_user
from app.core.exceptions import EntityNotFoundError

router = APIRouter(tags=["Dynamic Learning Paths & Dashboards"])


@router.post(
    "/learning-paths/generate",
    response_model=LearningGoalResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate Personalized Learning Path from Goal",
)
async def generate_learning_path(
    request: LearningGoalCreateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: LearningPathService = Depends(lambda: learning_path_service),
):
    """
    Onboarding entrypoint:
    Takes free-text learning goal, target mastery level (Beginner/Intermediate/Expert/Interview Ready/Other),
    custom target, and profile attributes.
    Generates a deep hierarchical learning roadmap (Sections -> Topics) and persists to DB.
    """
    return await service.create_goal_and_generate_path(
        user_id=current_user.user_id,
        request=request,
    )


@router.get(
    "/learning-paths/active",
    response_model=Optional[LearningPathResponse],
    summary="Get Authenticated Learner's Active Hierarchical Learning Path",
)
async def get_active_learning_path(
    current_user: CurrentUser = Depends(get_current_user),
    service: LearningPathService = Depends(lambda: learning_path_service),
):
    """
    Returns the active hierarchical roadmap including sections, granular topics,
    prerequisites, objectives, mastery scores, and live completion progress.
    """
    return await service.get_active_path_response(user_id=current_user.user_id)


@router.get(
    "/learning-paths/{path_id}",
    response_model=LearningPathResponse,
    summary="Get Hierarchical Learning Path by ID",
)
async def get_learning_path_by_id(
    path_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    service: LearningPathService = Depends(lambda: learning_path_service),
):
    """Returns a specific hierarchical learning path by ID."""
    return await service.get_path_by_id_response(path_id=path_id, user_id=current_user.user_id)


@router.get(
    "/home/dashboard",
    response_model=HomeDashboardResponse,
    summary="Get Personalized Home Dashboard Metrics",
)
async def get_home_dashboard(
    current_user: CurrentUser = Depends(get_current_user),
    analytics: TwinAnalyticsService = Depends(lambda: twin_analytics_service),
):
    """
    SkillTwin Home Screen Source-of-Truth:
    Returns non-fabricated learner metrics derived directly from database progress:
    - Active goal and target level
    - Current module and topic
    - Real overall progress (0.0 to 1.0) and mastery
    - Real streak and learning minutes
    - Weak areas and revision count
    - Contextual next best action
    """
    return await analytics.get_home_dashboard(user_id=current_user.user_id)


@router.get(
    "/twin/dashboard",
    response_model=TwinDashboardResponse,
    summary="Get Cognitive Twin Verified Model",
)
async def get_twin_dashboard(
    current_user: CurrentUser = Depends(get_current_user),
    analytics: TwinAnalyticsService = Depends(lambda: twin_analytics_service),
):
    """
    SkillTwin Cognitive Twin Source-of-Truth:
    Returns true empirical mastery model without vanity inflation.
    If learner has no completed topics, returns has_sufficient_data=False.
    """
    return await analytics.get_twin_dashboard(user_id=current_user.user_id)
