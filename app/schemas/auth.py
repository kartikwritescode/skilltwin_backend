from typing import Optional
from pydantic import BaseModel, Field
from app.schemas.profile import UserProfileResponse


class SignupRequest(BaseModel):
    email: str = Field(..., min_length=3)
    password: str = Field(..., min_length=6)
    name: Optional[str] = "Learner"


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3)
    password: str


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserProfileResponse
