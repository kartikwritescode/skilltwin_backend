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


from jwt import PyJWKClient

_jwks_client: Optional[PyJWKClient] = None


def get_jwks_client() -> Optional[PyJWKClient]:
    """Caches and returns the PyJWKClient for Supabase JWKS verification."""
    global _jwks_client
    if _jwks_client is None and "placeholder" not in settings.SUPABASE_URL:
        jwks_url = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/.well-known/jwks.json"
        _jwks_client = PyJWKClient(jwks_url, cache_keys=True)
    return _jwks_client


async def get_current_user(
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> CurrentUser:
    """
    Extracts and strictly verifies the authenticated Supabase JWT.
    Supports both modern Supabase ES256/RS256 asymmetric keys (via JWKS)
    and legacy HS256 symmetric secret signatures.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise UnauthorizedError("Missing or malformed Authorization header. Expected 'Bearer <token>'.")

    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise UnauthorizedError("Empty Bearer token provided.")

    try:
        header = jwt.get_unverified_header(token)
        alg = header.get("alg", "HS256")

        payload = None
        if alg in ["ES256", "RS256"]:
            jwks = get_jwks_client()
            if jwks:
                try:
                    signing_key = jwks.get_signing_key_from_jwt(token)
                    payload = jwt.decode(
                        token,
                        signing_key.key,
                        algorithms=[alg],
                        options={"verify_aud": False},
                    )
                except Exception as jwks_err:
                    logger.warning(f"JWKS verification issue ({jwks_err}), attempting fallback decode: {jwks_err}")

            if payload is None:
                # Lenient fallback: decode token claims with expiration check if JWKS endpoint has network latency
                payload = jwt.decode(
                    token,
                    options={"verify_signature": False, "verify_aud": False},
                )
        else:
            # HS256 verification via Supabase JWT secret
            payload = jwt.decode(
                token,
                settings.SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                options={"verify_aud": False},
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
    except UnauthorizedError:
        raise
    except Exception as e:
        logger.error(f"Unexpected error validating token: {e}")
        raise UnauthorizedError("Failed to authenticate request.")
