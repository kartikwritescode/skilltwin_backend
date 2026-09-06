import uuid
from typing import Optional, List
from app.repositories.goal_repository import GoalRepository, goal_repository
from app.repositories.user_repository import UserRepository, user_repository
from app.domain.goals.models import Goal, GoalStatus
from app.domain.journeys.models import GenerationStatus
from app.schemas.goals import GoalCreateRequest, GoalUpdateRequest, GoalResponse
from app.services.journey_service import JourneyService, journey_service
from app.core.exceptions import EntityNotFoundError, UnauthorizedError, ValidationError
from app.core.logging import logger


class GoalService:
    def __init__(
        self,
        goal_repo: GoalRepository = goal_repository,
        user_repo: UserRepository = user_repository,
        journey_svc: JourneyService = journey_service,
    ):
        self.goal_repo = goal_repo
        self.user_repo = user_repo
        self.journey_svc = journey_svc

    async def create_goal(self, user_id: str, request: GoalCreateRequest) -> GoalResponse:
        # 1. Validate user
        if not user_id or not user_id.strip():
            raise ValidationError("A valid authenticated user_id is required to create a goal.")
        
        # Ensure user profile exists or is initialized
        await self.user_repo.get_or_create(user_id=user_id, email=f"{user_id}@skilltwin.internal")

        logger.info(f"Creating goal for user {user_id}: '{request.title}'")

        # 2. Persist goal
        goal_id = f"goal_{uuid.uuid4().hex[:10]}"
        goal = Goal(
            id=goal_id,
            user_id=user_id,
            title=request.title.strip(),
            description=request.description,
            deadline=request.deadline,
            current_level=request.current_level,
            daily_minutes=request.daily_minutes,
            existing_knowledge=request.existing_knowledge,
            constraints=request.constraints or [],
            status=GoalStatus.ACTIVE,
            metadata={},
        )
        await self.goal_repo.save(goal)

        # 3. Create an initial journey record (status: PENDING)
        journey = await self.journey_svc.create_initial_journey(goal)

        # 4. Trigger journey generation asynchronously (non-blocking)
        self.journey_svc.trigger_async_generation(journey.id, goal)

        # 5. Return goal + journey generation status immediately
        return GoalResponse(
            id=goal.id,
            user_id=goal.user_id,
            title=goal.title,
            description=goal.description,
            deadline=goal.deadline,
            daily_minutes=goal.daily_minutes,
            current_level=goal.current_level,
            existing_knowledge=goal.existing_knowledge,
            constraints=goal.constraints,
            status=goal.status,
            active_journey_id=journey.id,
            generation_status=journey.generation_status,
            metadata=goal.metadata,
            created_at=goal.created_at,
            updated_at=goal.updated_at,
        )

    async def get_goal(self, user_id: str, goal_id: str) -> GoalResponse:
        goal = await self.goal_repo.get_by_id(goal_id)
        if not goal:
            raise EntityNotFoundError("Goal", goal_id)

        # Enforce authenticated identity validation
        if goal.user_id != user_id:
            logger.warning(f"User {user_id} attempted unauthorized access to goal {goal_id} (owned by {goal.user_id})")
            raise UnauthorizedError("You are not authorized to view this goal.")

        journey = await self.journey_svc.get_journey_by_goal(goal_id)
        gen_status = journey.generation_status if journey else GenerationStatus.PENDING

        return GoalResponse(
            id=goal.id,
            user_id=goal.user_id,
            title=goal.title,
            description=goal.description,
            deadline=goal.deadline,
            daily_minutes=goal.daily_minutes,
            current_level=goal.current_level,
            existing_knowledge=goal.existing_knowledge,
            constraints=goal.constraints,
            status=goal.status,
            active_journey_id=journey.id if journey else None,
            generation_status=gen_status,
            metadata=goal.metadata,
            created_at=goal.created_at,
            updated_at=goal.updated_at,
        )

    async def list_goals_for_user(self, user_id: str) -> List[GoalResponse]:
        goals = await self.goal_repo.list_by_user_id(user_id)
        responses = []
        for g in goals:
            j = await self.journey_svc.get_journey_by_goal(g.id)
            responses.append(
                GoalResponse(
                    id=g.id,
                    user_id=g.user_id,
                    title=g.title,
                    description=g.description,
                    deadline=g.deadline,
                    daily_minutes=g.daily_minutes,
                    current_level=g.current_level,
                    existing_knowledge=g.existing_knowledge,
                    constraints=g.constraints,
                    status=g.status,
                    active_journey_id=j.id if j else None,
                    generation_status=j.generation_status if j else GenerationStatus.PENDING,
                    metadata=g.metadata,
                    created_at=g.created_at,
                    updated_at=g.updated_at,
                )
            )
        return responses

    async def patch_goal(self, user_id: str, goal_id: str, request: GoalUpdateRequest) -> GoalResponse:
        goal = await self.goal_repo.get_by_id(goal_id)
        if not goal:
            raise EntityNotFoundError("Goal", goal_id)

        if goal.user_id != user_id:
            logger.warning(f"User {user_id} attempted unauthorized update on goal {goal_id}")
            raise UnauthorizedError("You are not authorized to modify this goal.")

        if request.title is not None:
            goal.title = request.title.strip()
        if request.description is not None:
            goal.description = request.description
        if request.deadline is not None:
            goal.deadline = request.deadline
        if request.daily_minutes is not None:
            goal.daily_minutes = request.daily_minutes
        if request.current_level is not None:
            goal.current_level = request.current_level
        if request.existing_knowledge is not None:
            goal.existing_knowledge = request.existing_knowledge
        if request.constraints is not None:
            goal.constraints = request.constraints
        if request.status is not None:
            goal.status = request.status

        await self.goal_repo.save(goal)
        logger.info(f"Updated goal {goal_id} for user {user_id}")

        journey = await self.journey_svc.get_journey_by_goal(goal_id)
        return GoalResponse(
            id=goal.id,
            user_id=goal.user_id,
            title=goal.title,
            description=goal.description,
            deadline=goal.deadline,
            daily_minutes=goal.daily_minutes,
            current_level=goal.current_level,
            existing_knowledge=goal.existing_knowledge,
            constraints=goal.constraints,
            status=goal.status,
            active_journey_id=journey.id if journey else None,
            generation_status=journey.generation_status if journey else GenerationStatus.PENDING,
            metadata=goal.metadata,
            created_at=goal.created_at,
            updated_at=goal.updated_at,
        )


goal_service = GoalService()
