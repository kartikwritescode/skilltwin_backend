from datetime import timedelta
import pytest
from httpx import AsyncClient
import jwt
from app.core.config import settings
from app.core.security import create_access_token


@pytest.mark.asyncio
async def test_auth_valid_jwt(async_client: AsyncClient):
    token = create_access_token(user_id="test_jwt_user_123", email="jwt_user@skilltwin.ai")
    headers = {"Authorization": f"Bearer {token}"}
    
    response = await async_client.get("/api/v1/profile", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "test_jwt_user_123"
    assert data["email"] == "jwt_user@skilltwin.ai"


@pytest.mark.asyncio
async def test_auth_missing_header(async_client: AsyncClient):
    response = await async_client.get("/api/v1/profile")
    assert response.status_code == 401
    data = response.json()
    assert data["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_auth_invalid_signature(async_client: AsyncClient):
    # Sign token with wrong secret
    tampered_token = jwt.encode(
        {"sub": "attacker_id", "email": "attacker@evil.com"},
        "wrong-secret-key-that-is-at-least-32-bytes-long!",
        algorithm="HS256"
    )
    response = await async_client.get("/api/v1/profile", headers={"Authorization": f"Bearer {tampered_token}"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_auth_expired_token(async_client: AsyncClient):
    # Expired 1 hour ago
    expired_token = create_access_token(
        user_id="expired_user",
        expires_delta=timedelta(hours=-1)
    )
    response = await async_client.get("/api/v1/profile", headers={"Authorization": f"Bearer {expired_token}"})
    assert response.status_code == 401
    assert "expired" in response.json()["error"]["message"].lower()


@pytest.mark.asyncio
async def test_auth_never_trusts_client_user_id_override(async_client: AsyncClient):
    # Legitimate authenticated identity
    real_user_id = "real_authenticated_user_01"
    token = create_access_token(user_id=real_user_id, email="real@skilltwin.ai")

    # Attacker tries to pass another user ID in headers or query
    headers = {
        "Authorization": f"Bearer {token}",
        "X-User-Id": "spoofed_target_victim_99"
    }

    response = await async_client.get("/api/v1/profile", headers=headers)
    assert response.status_code == 200
    data = response.json()
    # MUST resolve to real authenticated user, never the spoofed header
    assert data["id"] == real_user_id
    assert data["id"] != "spoofed_target_victim_99"
