from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
import jwt
from fastapi import Header
from app.core.config import settings
from app.core.exceptions import UnauthorizedError
from app.core.logging import logger


class CurrentUser:
    """Represents the authenticated learner session verified via Supabase JWT."""
    def __init__(self, user_id: str, email: str, role: str = "authenticated", claims: Optional[Dict[str, Any]] = None):
        self.user_id = user_id
        self.email = email
        self.role = role
        self.claims = claims or {}

    def __repr__(self) -> str:
        return f"<CurrentUser user_id={self.user_id} email={self.email} role={self.role}>"


def create_access_token(
    user_id: str,
    email: Optional[str] = None,
    role: str = "authenticated",
    expires_delta: Optional[timedelta] = None
) -> str:
    """Helper to generate standard Supabase-compliant JWTs (useful for tests and development)."""
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(hours=24))
    payload = {
        "sub": user_id,
        "email": email or f"{user_id}@skilltwin.internal",
        "role": role,
        "aud": "authenticated",
        "iss": "supabase",
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    return jwt.encode(payload, settings.SUPABASE_JWT_SECRET, algorithm="HS256")


async def get_current_user(
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> CurrentUser:
    """
    Extracts and strictly verifies the authenticated Supabase JWT.
    Never trusts client-supplied user_id or arbitrary unverified headers.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise UnauthorizedError("Missing or malformed Authorization header. Expected 'Bearer <token>'.")

    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise UnauthorizedError("Empty Bearer token provided.")

    try:
        # Decode and verify Supabase JWT
        # In Supabase, audience is typically "authenticated"
        payload = jwt.decode(
            token,
            settings.SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            options={"verify_aud": False}  # Lenient on custom aud, strict on sub/exp/signature
        )

        user_id = payload.get("sub")
        if not user_id:
            logger.warning("Supabase JWT missing 'sub' claim.")
            raise UnauthorizedError("Invalid token payload: missing subject ('sub') claim.")

        email = payload.get("email", f"{user_id}@skilltwin.internal")
        role = payload.get("role", "authenticated")

        return CurrentUser(user_id=str(user_id), email=email, role=role, claims=payload)

    except jwt.ExpiredSignatureError:
        logger.warning("Supabase JWT expired.")
        raise UnauthorizedError("Authentication token has expired.")
    except jwt.InvalidTokenError as e:
        logger.warning(f"Invalid Supabase JWT rejected: {e}")
        raise UnauthorizedError(f"Invalid authentication token: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error validating token: {e}")
        raise UnauthorizedError("Failed to authenticate request.")
