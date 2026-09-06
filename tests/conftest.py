import sys
from pathlib import Path
import pytest
from httpx import AsyncClient, ASGITransport

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.main import app
from app.core.security import create_access_token


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.fixture
def auth_headers():
    token = create_access_token(user_id="default_learner_01", email="default_learner_01@skilltwin.ai")
    return {
        "Authorization": f"Bearer {token}"
    }


@pytest.fixture
def secondary_auth_headers():
    token = create_access_token(user_id="other_learner_02", email="other_learner_02@skilltwin.ai")
    return {
        "Authorization": f"Bearer {token}"
    }
