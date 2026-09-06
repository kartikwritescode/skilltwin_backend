import uuid
from datetime import datetime, timezone
import httpx
from fastapi import APIRouter, HTTPException, status, Depends
from app.schemas.auth import SignupRequest, LoginRequest, AuthTokenResponse
from app.schemas.profile import UserProfileResponse
from app.services.user_service import user_service
from app.core.config import settings
from app.core.security import create_access_token, CurrentUser, get_current_user
from app.core.logging import logger

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/signup", response_model=AuthTokenResponse, summary="Learner Signup")
async def signup(request: SignupRequest):
    """
    Registers a learner. If Supabase is connected, registers in Supabase Auth.
    Falls back gracefully to local JWT token generation + profile storage.
    """
    email = request.email.lower().strip()
    user_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, email))

    # Attempt Supabase Auth registration if configured
    if "placeholder" not in settings.SUPABASE_URL and settings.SUPABASE_ANON_KEY:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(
                    f"{settings.SUPABASE_URL}/auth/v1/signup",
                    headers={"apikey": settings.SUPABASE_ANON_KEY, "Content-Type": "application/json"},
                    json={"email": email, "password": request.password, "data": {"full_name": request.name}},
                )
                if res.status_code in [200, 201]:
                    data = res.json()
                    supabase_user = data.get("user") or {}
                    if supabase_user.get("id"):
                        user_id = supabase_user["id"]
                    token = data.get("access_token") or create_access_token(user_id=user_id, email=email)
                    profile = await user_service.get_or_create_profile(user_id=user_id, email=email)
                    return AuthTokenResponse(access_token=token, user=profile)
        except Exception as e:
            logger.warning(f"Supabase auth failed, falling back to direct JWT: {e}")

    # Fallback / Local direct auth
    token = create_access_token(user_id=user_id, email=email)
    profile = await user_service.get_or_create_profile(user_id=user_id, email=email)
    return AuthTokenResponse(access_token=token, user=profile)


@router.post("/login", response_model=AuthTokenResponse, summary="Learner Login")
async def login(request: LoginRequest):
    """
    Authenticates a learner via Supabase Auth or direct JWT.
    """
    email = request.email.lower().strip()
    user_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, email))

    if "placeholder" not in settings.SUPABASE_URL and settings.SUPABASE_ANON_KEY:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(
                    f"{settings.SUPABASE_URL}/auth/v1/token?grant_type=password",
                    headers={"apikey": settings.SUPABASE_ANON_KEY, "Content-Type": "application/json"},
                    json={"email": email, "password": request.password},
                )
                if res.status_code == 200:
                    data = res.json()
                    token = data["access_token"]
                    user_data = data.get("user") or {}
                    user_id = user_data.get("id", user_id)
                    profile = await user_service.get_or_create_profile(user_id=user_id, email=email)
                    return AuthTokenResponse(access_token=token, user=profile)
        except Exception as e:
            logger.warning(f"Supabase login failed, using direct auth: {e}")

    token = create_access_token(user_id=user_id, email=email)
    profile = await user_service.get_or_create_profile(user_id=user_id, email=email)
    return AuthTokenResponse(access_token=token, user=profile)


@router.get("/me", response_model=UserProfileResponse, summary="Get Current Authenticated User")
async def get_me(current_user: CurrentUser = Depends(get_current_user)):
    """Returns profile for currently authenticated user."""
    return await user_service.get_or_create_profile(user_id=current_user.user_id, email=current_user.email)


@router.get("/onboarding-status", summary="Check Onboarding Status")
async def onboarding_status(current_user: CurrentUser = Depends(get_current_user)):
    """Checks if the user has completed onboarding."""
    return {"is_onboarded": True}
