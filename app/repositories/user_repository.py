from datetime import datetime, timezone
from typing import Optional, Dict
from app.domain.users.models import UserProfile
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[UserProfile, str]):
    def __init__(self):
        self._users: Dict[str, UserProfile] = {}
        # Seed default test user profile
        self._seed_default_user()

    def _seed_default_user(self):
        default_user = UserProfile(
            id="usr_test_default_01",
            email="learner@skilltwin.ai",
            full_name="Alex Learner",
            timezone="UTC",
            preferences={"daily_reminder_hour": 9, "theme": "system"},
        )
        self._users[default_user.id] = default_user

    async def get_by_id(self, entity_id: str) -> Optional[UserProfile]:
        return self._users.get(entity_id)

    async def list_all(self):
        return list(self._users.values())

    async def save(self, entity: UserProfile) -> UserProfile:
        entity.updated_at = datetime.now(timezone.utc)
        self._users[entity.id] = entity
        return entity

    async def get_or_create(self, user_id: str, email: str, full_name: Optional[str] = None) -> UserProfile:
        if user_id in self._users:
            profile = self._users[user_id]
            if email and (profile.email.endswith(".internal") or not profile.email):
                profile.email = email
            return profile
        
        new_profile = UserProfile(
            id=user_id,
            email=email,
            full_name=full_name or email.split("@")[0].capitalize(),
            timezone="UTC",
            preferences={},
        )
        self._users[user_id] = new_profile
        return new_profile

    async def delete(self, entity_id: str) -> bool:
        if entity_id in self._users:
            del self._users[entity_id]
            return True
        return False


user_repository = UserRepository()
