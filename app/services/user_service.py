from typing import Optional, Dict, Any
from app.repositories.user_repository import UserRepository, user_repository
from app.schemas.profile import UserProfileResponse, UserProfileUpdateRequest
from app.core.logging import logger


class UserService:
    def __init__(self, repo: UserRepository = user_repository):
        self.repo = repo

    async def get_or_create_profile(self, user_id: str, email: str) -> UserProfileResponse:
        logger.info(f"Resolving profile for user: {user_id}")
        profile = await self.repo.get_or_create(user_id=user_id, email=email)
        return UserProfileResponse(
            id=profile.id,
            email=profile.email,
            full_name=profile.full_name,
            timezone=profile.timezone,
            preferences=profile.preferences,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )

    async def update_profile(
        self, user_id: str, update_data: UserProfileUpdateRequest
    ) -> UserProfileResponse:
        profile = await self.repo.get_by_id(user_id)
        if not profile:
            profile = await self.repo.get_or_create(user_id=user_id, email=f"{user_id}@skilltwin.internal")

        if update_data.full_name is not None:
            profile.full_name = update_data.full_name
        if update_data.timezone is not None:
            profile.timezone = update_data.timezone
        if update_data.preferences is not None:
            profile.preferences.update(update_data.preferences)

        await self.repo.save(profile)
        return UserProfileResponse(
            id=profile.id,
            email=profile.email,
            full_name=profile.full_name,
            timezone=profile.timezone,
            preferences=profile.preferences,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        )


user_service = UserService()
