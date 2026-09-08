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
                    profile = await user_service.get_or_create_profile(user_id=user_id, email=email, full_name=request.name)
                    logger.info(f"Supabase registration successful for {email} (id: {user_id})")
                    return AuthTokenResponse(access_token=token, user=profile)
                elif res.status_code == 422 and "user_already_exists" in res.text:
                    logger.info(f"User {email} already registered in Supabase, attempting login verification")
                    login_res = await client.post(
                        f"{settings.SUPABASE_URL}/auth/v1/token?grant_type=password",
                        headers={"apikey": settings.SUPABASE_ANON_KEY, "Content-Type": "application/json"},
                        json={"email": email, "password": request.password},
                    )
                    if login_res.status_code == 200:
                        login_data = login_res.json()
                        token = login_data["access_token"]
                        user_id = login_data.get("user", {}).get("id", user_id)
                        profile = await user_service.get_or_create_profile(user_id=user_id, email=email, full_name=request.name)
                        return AuthTokenResponse(access_token=token, user=profile)
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="An account with this email already exists. Please log in.",
                    )
                else:
                    err_msg = res.json().get("msg") or res.json().get("message") or "Signup validation failed"
                    logger.warning(f"Supabase signup rejected ({res.status_code}): {res.text}")
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err_msg)
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Supabase auth connection issue, falling back to direct JWT: {e}")

    # Fallback / Local direct auth
    token = create_access_token(user_id=user_id, email=email)
    profile = await user_service.get_or_create_profile(user_id=user_id, email=email, full_name=request.name)
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
                    logger.info(f"Supabase login successful for {email} (id: {user_id})")
                    return AuthTokenResponse(access_token=token, user=profile)
                elif res.status_code in [400, 401]:
                    logger.warning(f"Supabase login invalid credentials for {email}")
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid email or password.",
                    )
                else:
                    logger.warning(f"Supabase login returned unexpected status {res.status_code}: {res.text}")
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Supabase login failed, using direct auth: {e}")

    token = create_access_token(user_id=user_id, email=email)
    profile = await user_service.get_or_create_profile(user_id=user_id, email=email)
    return AuthTokenResponse(access_token=token, user=profile)


@router.get("/me", response_model=UserProfileResponse, summary="Get Current Authenticated User")
async def get_me(current_user: CurrentUser = Depends(get_current_user)):
    """Returns profile for currently authenticated user."""
    return await user_service.get_or_create_profile(user_id=current_user.user_id, email=current_user.email)


from app.repositories.dynamic_learning_repository import dynamic_learning_repo

@router.get("/onboarding-status", summary="Check Onboarding Status")
async def onboarding_status(current_user: CurrentUser = Depends(get_current_user)):
    """Checks if the user has completed onboarding by checking for an active learning path."""
    active_path = await dynamic_learning_repo.get_active_path_for_user(current_user.user_id)
    return {"is_onboarded": active_path is not None}
