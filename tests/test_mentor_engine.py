import pytest
from httpx import AsyncClient
from app.domain.mentor.models import ActionType
from app.ai.orchestrator.context_builder import MentorContextBuilder, MentorContext, PrerequisiteSummary
from app.services.recommendation_service import RecommendationService, recommendation_service
from app.repositories.recommendation_repository import recommendation_repository
from app.ai.schemas.ai_schemas import MentorRecommendationOutput
from app.ai.providers.mock_provider import MockLLMProvider


# ------------------------------------------------------------------------------
# 1. Deterministic Rule Tests
# ------------------------------------------------------------------------------

def test_deterministic_rule_remediate():
    service = RecommendationService()
    ctx = MentorContext(
        user_id="usr_01",
        goal_id="goal_01",
        goal_title="Flutter Architect",
        current_node_id="node_async",
        current_concept_id="concept_async",
        current_concept_mastery=20.0,
        prerequisites=[
            PrerequisiteSummary(
                node_id="node_dart_basics",
                concept_id="concept_dart_basics",
                title="Dart Basics",
                mastery=45.0,  # Below 60.0% threshold!
                is_satisfied=False,
            )
        ]
    )

    intent, concept_id, rule_name = service.evaluate_deterministic_rules(ctx)
    assert intent == ActionType.REMEDIATE
    assert concept_id == "concept_dart_basics"
    assert rule_name == "PREREQUISITE_DEFICIT"


def test_deterministic_rule_revise_on_high_retention_risk():
    service = RecommendationService()
    ctx = MentorContext(
        user_id="usr_01",
        goal_id="goal_01",
        goal_title="Flutter Architect",
        current_node_id="node_async",
        current_concept_id="concept_async",
        current_concept_mastery=50.0,
        prerequisites=[
            PrerequisiteSummary(
                node_id="node_prereq",
                concept_id="concept_prereq",
                title="OOP",
                mastery=85.0,
                is_satisfied=True,
            )
        ],
        due_retention_items=[
            {
                "concept_id": "concept_recursion",
                "concept_name": "Recursion",
                "retention_risk": "high",
                "interval_days": 1,
            }
        ]
    )

    intent, concept_id, rule_name = service.evaluate_deterministic_rules(ctx)
    assert intent == ActionType.REVISE
    assert concept_id == "concept_recursion"
    assert rule_name == "HIGH_RETENTION_RISK"


def test_deterministic_rule_prove_on_unverified_mastery():
    service = RecommendationService()
    ctx = MentorContext(
        user_id="usr_01",
        goal_id="goal_01",
        goal_title="Flutter Architect",
        current_node_id="node_async",
        current_concept_id="concept_async",
        current_concept_mastery=82.0,  # High mastery
        current_evidence_count=1,      # Weak evidence (< 2)
        prerequisites=[],
        due_retention_items=[],
    )

    intent, concept_id, rule_name = service.evaluate_deterministic_rules(ctx)
    assert intent == ActionType.PROVE
    assert concept_id == "concept_async"
    assert rule_name == "UNVERIFIED_MASTERY"


def test_deterministic_rule_practice_on_active_concept():
    service = RecommendationService()
    ctx = MentorContext(
        user_id="usr_01",
        goal_id="goal_01",
        goal_title="Flutter Architect",
        current_node_id="node_async",
        current_concept_id="concept_async",
        current_concept_mastery=55.0,  # Active practice range
        current_evidence_count=3,
        prerequisites=[],
        due_retention_items=[],
    )

    intent, concept_id, rule_name = service.evaluate_deterministic_rules(ctx)
    assert intent == ActionType.PRACTICE
    assert concept_id == "concept_async"
    assert rule_name == "ACTIVE_PRACTICE"


# ------------------------------------------------------------------------------
# 2. MentorContextBuilder Selective Token Efficiency
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_context_builder_selectivity():
    builder = MentorContextBuilder()
    context = await builder.build_context("default_learner_01")
    assert isinstance(context, MentorContext)
    assert context.user_id == "default_learner_01"

    # Context format should be concise, not an entire dump
    prompt_str = context.to_llm_prompt()
    assert len(prompt_str) < 3000
    assert "TARGET GOAL:" in prompt_str
    assert "CURRENT MILESTONE NODE:" in prompt_str


# ------------------------------------------------------------------------------
# 3. Pydantic Structured Output Validation
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_structured_llm_output_validation():
    provider = MockLLMProvider()
    structured = await provider.generate_structured(
        prompt="INTENT: REMEDIATE on concept recursion",
        response_schema=MentorRecommendationOutput,
    )
    assert isinstance(structured, MentorRecommendationOutput)
    assert structured.intent == "REMEDIATE"
    assert structured.confidence > 0.8
    assert len(structured.title) > 0
    assert len(structured.reason) > 0


# ------------------------------------------------------------------------------
# 4. Recommendation Persistence Audit Log
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recommendation_persistence(async_client: AsyncClient, auth_headers: dict):
    # Call GET /api/v1/mentor/today
    response = await async_client.get("/api/v1/mentor/today", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "recommended_action" in data

    # Verify recommendation was persisted in the repository audit log
    records = await recommendation_repository.list_by_user_id("default_learner_01")
    assert len(records) >= 1
    latest_rec = records[0]
    assert latest_rec.user_id == "default_learner_01"
    assert latest_rec.rule_matched is not None
    assert latest_rec.confidence > 0.0


# ------------------------------------------------------------------------------
# 5. Contextual Mentor Chat Messaging
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_contextual_mentor_chat(async_client: AsyncClient, auth_headers: dict):
    payload = {
        "message": "I'm finding streams difficult to debug. How should I approach it?",
        "context": {"screen": "journey_node_view"}
    }
    response = await async_client.post("/api/v1/mentor/message", json=payload, headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "mentor"
    assert len(data["content"]) > 10
    assert len(data["suggested_actions"]) > 0
