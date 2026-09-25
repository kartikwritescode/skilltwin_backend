import pytest
import uuid
from datetime import date, timedelta
from app.core.database import get_session_factory
from app.core.db_models import GoalModel, ProfileModel, MicroSubgraphModel, CanonicalOntologyModel


@pytest.fixture
async def seeded_user_and_goal():
    session_factory = get_session_factory()
    user_id = "default_learner_01"
    goal_id = str(uuid.uuid4())

    async with session_factory() as session:
        # Ensure Profile exists
        profile = await session.get(ProfileModel, user_id)
        if not profile:
            profile = ProfileModel(
                id=user_id,
                email="default_learner_01@skilltwin.ai",
                display_name="Test Learner",
            )
            session.add(profile)

        # Create Goal
        goal = GoalModel(
            id=goal_id,
            user_id=user_id,
            title="Frontend React & Next.js Architecture",
            description="Master modern React, component trees, state hooks, and routing",
            deadline=date.today() + timedelta(days=30),
            daily_minutes=30,
            current_level="beginner",
            target_level="intermediate",
        )
        session.add(goal)

        # Ensure at least 2 micro-subgraphs exist for assembly
        ont = await session.get(CanonicalOntologyModel, "ontology_test_frontend")
        if not ont:
            ont = CanonicalOntologyModel(
                id="ontology_test_frontend",
                domain="frontend",
                title="Frontend Web Development",
                description="Frontend React and Web architecture",
            )
            session.add(ont)

        sg1 = await session.get(MicroSubgraphModel, "subgraph_test_react_components")
        if not sg1:
            sg1 = MicroSubgraphModel(
                id="subgraph_test_react_components",
                ontology_id="ontology_test_frontend",
                slug="test-react-components",
                title="Frontend React: Core Components",
                tier="foundational",
                estimated_minutes=30,
                prerequisites=[],
            )
            session.add(sg1)

        sg2 = await session.get(MicroSubgraphModel, "subgraph_test_react_hooks")
        if not sg2:
            sg2 = MicroSubgraphModel(
                id="subgraph_test_react_hooks",
                ontology_id="ontology_test_frontend",
                slug="test-react-hooks",
                title="Frontend React: Advanced Hooks",
                tier="core",
                estimated_minutes=45,
                prerequisites=["test-react-components"],
            )
            session.add(sg2)

        await session.commit()

    return {"user_id": user_id, "goal_id": goal_id}


@pytest.mark.asyncio
async def test_generate_adaptive_path(async_client, auth_headers, seeded_user_and_goal):
    goal_id = seeded_user_and_goal["goal_id"]

    response = await async_client.post(
        "/api/v1/adaptive-paths/generate",
        headers=auth_headers,
        json={
            "goal_id": goal_id,
            "daily_budget_minutes": 30,
        },
    )

    assert response.status_code == 201, response.text
    data = response.json()

    assert data["goal_id"] == goal_id
    assert data["status"] == "ACTIVE"
    assert len(data["nodes"]) >= 2
    assert len(data["edges"]) >= 1

    # Check node ordering and states
    nodes = data["nodes"]
    assert nodes[0]["order_index"] == 0
    assert nodes[0]["state"] == "CURRENT"

    # First node should have non-null concept_id and title
    assert nodes[0]["concept_id"]
    assert nodes[0]["title"]


@pytest.mark.asyncio
async def test_get_adaptive_path(async_client, auth_headers, seeded_user_and_goal):
    goal_id = seeded_user_and_goal["goal_id"]

    # 1. Generate path
    gen_resp = await async_client.post(
        "/api/v1/adaptive-paths/generate",
        headers=auth_headers,
        json={"goal_id": goal_id},
    )
    assert gen_resp.status_code == 201
    path_id = gen_resp.json()["id"]

    # 2. Get path
    get_resp = await async_client.get(
        f"/api/v1/adaptive-paths/{path_id}",
        headers=auth_headers,
    )
    assert get_resp.status_code == 200
    data = get_resp.json()

    assert data["id"] == path_id
    assert len(data["nodes"]) >= 2
    assert "velocity_metrics" in data
    assert data["velocity_metrics"]["velocity_factor"] >= 0.5


@pytest.mark.asyncio
async def test_expand_node_content(async_client, auth_headers, seeded_user_and_goal):
    goal_id = seeded_user_and_goal["goal_id"]

    gen_resp = await async_client.post(
        "/api/v1/adaptive-paths/generate",
        headers=auth_headers,
        json={"goal_id": goal_id},
    )
    path_data = gen_resp.json()
    path_id = path_data["id"]
    node_id = path_data["nodes"][0]["id"]

    # Trigger expansion
    expand_resp = await async_client.post(
        f"/api/v1/adaptive-paths/{path_id}/nodes/{node_id}/expand",
        headers=auth_headers,
    )
    assert expand_resp.status_code == 200, expand_resp.text
    expand_data = expand_resp.json()

    assert expand_data["node_id"] == node_id
    assert expand_data["is_elaborated"] is True
    assert "content" in expand_data
    assert "explanation_markdown" in expand_data["content"]
    assert len(expand_data["content"]["practice_questions"]) > 0


@pytest.mark.asyncio
async def test_submit_node_evidence_and_mutation(async_client, auth_headers, seeded_user_and_goal):
    goal_id = seeded_user_and_goal["goal_id"]

    gen_resp = await async_client.post(
        "/api/v1/adaptive-paths/generate",
        headers=auth_headers,
        json={"goal_id": goal_id},
    )
    path_data = gen_resp.json()
    path_id = path_data["id"]
    node_id = path_data["nodes"][0]["id"]

    # Submit evidence that triggers remediation detour (score < 0.50)
    ev_resp = await async_client.post(
        f"/api/v1/adaptive-paths/{path_id}/nodes/{node_id}/evidence",
        headers=auth_headers,
        json={
            "score": 0.35,
            "confidence": 0.5,
            "duration_seconds": 180,
            "misconceptions": ["state_mutability_confusion"],
        },
    )
    assert ev_resp.status_code == 200, ev_resp.text
    mutation = ev_resp.json()

    assert mutation["action"] == "REMEDIATION_SPLICED"
    assert mutation["path_id"] == path_id
    assert mutation["node_id"] == node_id
    assert "remediation_node_id" in mutation
    assert "remediation_node_title" in mutation

    # Verify the path and node states in DB
    get_resp = await async_client.get(
        f"/api/v1/adaptive-paths/{path_id}",
        headers=auth_headers,
    )
    assert get_resp.status_code == 200
    updated_nodes = {n["id"]: n for n in get_resp.json()["nodes"]}
    # Spliced node should exist and have is_remediation=True
    rem_id = mutation["remediation_node_id"]
    assert rem_id in updated_nodes
    assert updated_nodes[rem_id]["is_remediation"] is True
    # The failed node should have state REMEDIATING
    assert updated_nodes[node_id]["state"] == "REMEDIATING"


@pytest.mark.asyncio
async def test_get_pacing_status(async_client, auth_headers, seeded_user_and_goal):
    goal_id = seeded_user_and_goal["goal_id"]

    gen_resp = await async_client.post(
        "/api/v1/adaptive-paths/generate",
        headers=auth_headers,
        json={"goal_id": goal_id},
    )
    path_id = gen_resp.json()["id"]

    pacing_resp = await async_client.get(
        f"/api/v1/adaptive-paths/{path_id}/pacing-status",
        headers=auth_headers,
    )
    assert pacing_resp.status_code == 200, pacing_resp.text
    data = pacing_resp.json()

    assert "timeline" in data
    assert data["timeline"]["path_id"] == path_id
    assert "daily_pace_minutes" in data["timeline"]
