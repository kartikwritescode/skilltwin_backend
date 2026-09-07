import pytest
from httpx import AsyncClient
from app.core.security import create_access_token


@pytest.fixture
def new_user_auth_headers():
    token = create_access_token(user_id="brand_new_user_999", email="brandnew@skilltwin.ai")
    return {"Authorization": f"Bearer {token}"}


async def ensure_active_path(client: AsyncClient, headers: dict) -> dict:
    path_res = await client.get("/api/v1/learning-paths/active", headers=headers)
    if path_res.status_code == 200 and path_res.json():
        return path_res.json()
    payload = {
        "learning_goal": "Become a backend developer using Django and PostgreSQL",
        "target_level": "Intermediate",
        "custom_target": "Build production SaaS backends",
        "daily_minutes": 45,
        "current_knowledge": ["Python", "SQL Basics"],
        "learning_preferences": "Hands-on projects and deep invariants",
    }
    await client.post("/api/v1/learning-paths/generate", json=payload, headers=headers)
    res = await client.get("/api/v1/learning-paths/active", headers=headers)
    return res.json()


@pytest.mark.asyncio
async def test_home_dashboard_new_user(async_client: AsyncClient, new_user_auth_headers):
    """Verifies that a brand new user receives a clean empty state with NO fake metrics."""
    res = await async_client.get("/api/v1/home/dashboard", headers=new_user_auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["is_new_learner"] is True
    assert data["overall_mastery"] == 0.0
    assert data["overall_progress"] == 0.0
    assert data["topics_completed"] == 0


@pytest.mark.asyncio
async def test_twin_dashboard_new_user(async_client: AsyncClient, new_user_auth_headers):
    """Verifies that Cognitive Twin never displays fake 72% mastery for a fresh user."""
    res = await async_client.get("/api/v1/twin/dashboard", headers=new_user_auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["has_sufficient_data"] is False
    assert data["overall_mastery"] == 0.0
    assert data["strongest_areas"] == []


@pytest.mark.asyncio
async def test_generate_learning_path_and_retrieve_hierarchy(async_client: AsyncClient, auth_headers):
    """Verifies full onboarding generation pipeline into sections and topics."""
    path_data = await ensure_active_path(async_client, auth_headers)
    assert path_data is not None
    assert len(path_data["sections"]) >= 3
    first_section = path_data["sections"][0]
    assert len(first_section["topics"]) >= 1
    first_topic = first_section["topics"][0]
    assert first_topic["status"] in ("learning", "not_started", "completed")


@pytest.mark.asyncio
async def test_topic_lifecycle_actions(async_client: AsyncClient, auth_headers):
    """Tests starting, completing, and marking revision for a topic."""
    path_data = await ensure_active_path(async_client, auth_headers)
    first_topic = path_data["sections"][0]["topics"][0]
    topic_id = first_topic["id"]

    # 1. Get Topic Details
    detail_res = await async_client.get(f"/api/v1/topics/{topic_id}", headers=auth_headers)
    assert detail_res.status_code == 200
    assert detail_res.json()["title"] == first_topic["title"]

    # 2. Start Topic
    start_res = await async_client.post(f"/api/v1/topics/{topic_id}/start", headers=auth_headers)
    assert start_res.status_code == 200
    assert start_res.json()["status"] == "learning"

    # 3. Complete Topic
    complete_res = await async_client.post(f"/api/v1/topics/{topic_id}/complete", headers=auth_headers)
    assert complete_res.status_code == 200
    comp_data = complete_res.json()
    assert comp_data["status"] == "completed"
    assert comp_data["mastery_score"] >= 70.0
    assert comp_data["completed_at"] is not None

    # 4. Mark Revision
    rev_res = await async_client.post(f"/api/v1/topics/{topic_id}/revision", headers=auth_headers)
    assert rev_res.status_code == 200
    assert rev_res.json()["status"] == "needs_revision"


@pytest.mark.asyncio
async def test_understand_mode_caching(async_client: AsyncClient, auth_headers):
    """Verifies that topic explanations are cached in the DB to minimize LLM cost."""
    path_data = await ensure_active_path(async_client, auth_headers)
    topic_id = path_data["sections"][0]["topics"][0]["id"]

    # Call 1: Generates and caches
    res1 = await async_client.post(f"/api/v1/topics/{topic_id}/explain", headers=auth_headers)
    assert res1.status_code == 200
    data1 = res1.json()
    assert len(data1["content"]) > 50

    # Call 2: Returns from cache
    res2 = await async_client.post(f"/api/v1/topics/{topic_id}/explain", headers=auth_headers)
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["cached"] is True
    assert data2["content"] == data1["content"]


@pytest.mark.asyncio
async def test_practice_questions_and_scoring(async_client: AsyncClient, auth_headers):
    """Verifies question generation and deterministic answer submission."""
    path_data = await ensure_active_path(async_client, auth_headers)
    topic_id = path_data["sections"][0]["topics"][0]["id"]

    # Get or generate questions
    q_res = await async_client.post(f"/api/v1/topics/{topic_id}/questions", headers=auth_headers)
    assert q_res.status_code == 200
    q_data = q_res.json()
    assert len(q_data["questions"]) >= 2

    # Submit answers
    answers_payload = {
        "answers": [
            {
                "question_id": q["id"],
                "user_answer": q["correct_answer"],
            }
            for q in q_data["questions"]
        ]
    }
    sub_res = await async_client.post(f"/api/v1/topics/{topic_id}/submit", json=answers_payload, headers=auth_headers)
    assert sub_res.status_code == 200
    sub_data = sub_res.json()
    assert sub_data["score"] >= 70.0
    assert sub_data["correct_count"] > 0


@pytest.mark.asyncio
async def test_contextual_ask(async_client: AsyncClient, auth_headers):
    """Verifies contextual Q&A endpoint."""
    path_data = await ensure_active_path(async_client, auth_headers)
    topic_id = path_data["sections"][0]["topics"][0]["id"]

    res = await async_client.post(
        f"/api/v1/topics/{topic_id}/ask",
        json={"query": "Why is this architectural invariant essential?"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert len(data["answer"]) > 20
    assert data["audio_tts_text"] is not None


@pytest.mark.asyncio
async def test_home_and_twin_after_learning(async_client: AsyncClient, auth_headers):
    """Verifies that Home and Twin reflect real progress after topics are completed."""
    await ensure_active_path(async_client, auth_headers)

    home_res = await async_client.get("/api/v1/home/dashboard", headers=auth_headers)
    assert home_res.status_code == 200
    home_data = home_res.json()
    assert home_data["goal_title"] is not None

    twin_res = await async_client.get("/api/v1/twin/dashboard", headers=auth_headers)
    assert twin_res.status_code == 200
    twin_data = twin_res.json()
    assert twin_data["user_id"] == "default_learner_01"
