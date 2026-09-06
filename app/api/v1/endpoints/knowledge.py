from fastapi import APIRouter, Depends
from app.core.security import CurrentUser, get_current_user
from app.schemas.knowledge import (
    KnowledgeMaintenanceResponse,
    GenerateNotesRequest,
    PersonalizedStudyNotesResponse,
)
from app.services.knowledge_maintenance_service import (
    KnowledgeMaintenanceService,
    knowledge_maintenance_service,
)

router = APIRouter(prefix="/knowledge", tags=["Knowledge Maintenance"])


@router.get(
    "/maintenance",
    response_model=KnowledgeMaintenanceResponse,
    summary="Get Personalized Knowledge Maintenance Posture",
)
async def get_knowledge_maintenance(
    current_user: CurrentUser = Depends(get_current_user),
    service: KnowledgeMaintenanceService = Depends(lambda: knowledge_maintenance_service),
):
    """
    Evaluates every concept in the learner's ecosystem against mastery, retention decay,
    goal relevance, prerequisites, known misconceptions, recent evidence, and journey position.
    
    Assigns each concept one of five strategic maintenance actions:
    - FIX: Active misconceptions or remediation nodes requiring immediate cognitive repair
    - REVISE: Mastered or in-progress concepts suffering retention decay or due for review
    - LEARN_NEXT: Unlocked next concepts in the learner's journey
    - KEEP: Strong mastery and fresh retention requiring no immediate action
    - DEPRIORITIZE: Irrelevant to active goals or deeply locked behind prerequisites
    """
    return await service.get_maintenance_overview(current_user.user_id)


@router.post(
    "/notes/generate",
    response_model=PersonalizedStudyNotesResponse,
    summary="Generate Personalized Study Notes",
)
async def generate_personalized_notes(
    request: GenerateNotesRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: KnowledgeMaintenanceService = Depends(lambda: knowledge_maintenance_service),
):
    """
    Synthesizes custom study notes tailored directly to the learner's state using:
    - Active goal context
    - Target concept definition
    - Semantic RAG source chunks retrieved from uploaded resources
    - Learner twin cognitive state (mastery, retention)
    - Specific diagnosed misconceptions and previous explanation evaluations

    Cached efficiently by user cognitive state to reduce redundant LLM calls.
    """
    return await service.generate_personalized_notes(
        user_id=current_user.user_id,
        concept_id=request.concept_id,
        force_regenerate=request.force_regenerate,
    )
