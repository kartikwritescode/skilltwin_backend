from fastapi import APIRouter, Depends, status
from app.schemas.dynamic_learning import (
    TopicDetailResponse,
    TopicStatusUpdateResponse,
    TopicExplanationResponse,
    TopicQuestionsResponse,
    QuestionSubmissionRequest,
    QuestionSubmissionResponse,
    ContextualAskRequest,
    ContextualAskResponse,
)
from app.services.topic_interaction_service import TopicInteractionService, topic_interaction_service
from app.core.security import CurrentUser, get_current_user

router = APIRouter(prefix="/topics", tags=["Topic Actions & Interactive Modes"])


@router.get(
    "/{topic_id}",
    response_model=TopicDetailResponse,
    summary="Get Detailed Topic Overview & Status",
)
async def get_topic_detail(
    topic_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    service: TopicInteractionService = Depends(lambda: topic_interaction_service),
):
    """Returns topic metadata, prerequisites, objectives, status, mastery, and navigation IDs."""
    return await service.get_topic_detail(user_id=current_user.user_id, topic_id=topic_id)


@router.post(
    "/{topic_id}/start",
    response_model=TopicStatusUpdateResponse,
    summary="Start Topic Session (status = learning)",
)
async def start_topic(
    topic_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    service: TopicInteractionService = Depends(lambda: topic_interaction_service),
):
    """Sets topic state to learning and records active session timestamp."""
    return await service.start_topic(user_id=current_user.user_id, topic_id=topic_id)


@router.post(
    "/{topic_id}/complete",
    response_model=TopicStatusUpdateResponse,
    summary="Mark Topic Completed (status = completed)",
)
async def complete_topic(
    topic_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    service: TopicInteractionService = Depends(lambda: topic_interaction_service),
):
    """
    Marks topic completed, schedules spaced repetition review, auto-unlocks next topic,
    and updates overall path progress.
    """
    return await service.complete_topic(user_id=current_user.user_id, topic_id=topic_id)


@router.post(
    "/{topic_id}/revision",
    response_model=TopicStatusUpdateResponse,
    summary="Mark Topic as Needs Revision (status = needs_revision)",
)
async def mark_topic_revision(
    topic_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    service: TopicInteractionService = Depends(lambda: topic_interaction_service),
):
    """Flags topic as needing revision and schedules immediate retrieval queue."""
    return await service.mark_revision(user_id=current_user.user_id, topic_id=topic_id)


@router.post(
    "/{topic_id}/explain",
    response_model=TopicExplanationResponse,
    summary="Understand Mode: Get Tailored Topic Explanation (Cached + RAG)",
)
async def get_topic_explanation(
    topic_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    service: TopicInteractionService = Depends(lambda: topic_interaction_service),
):
    """
    Returns tailored Socratic explanation.
    Checks DB cache first (Cost optimization); on miss, grounds against RAG knowledge chunks.
    """
    return await service.get_topic_explanation(user_id=current_user.user_id, topic_id=topic_id)


@router.post(
    "/{topic_id}/questions",
    response_model=TopicQuestionsResponse,
    summary="Questions Mode: Get Practice Test Suite (MCQ, Scenario, Code Fix, Interview)",
)
async def get_topic_questions(
    topic_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    service: TopicInteractionService = Depends(lambda: topic_interaction_service),
):
    """Returns stored practice questions or generates a balanced multi-format set."""
    return await service.get_or_generate_questions(user_id=current_user.user_id, topic_id=topic_id)


@router.post(
    "/{topic_id}/submit",
    response_model=QuestionSubmissionResponse,
    summary="Submit Practice Answers & Update Mastery",
)
async def submit_topic_answers(
    topic_id: str,
    request: QuestionSubmissionRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: TopicInteractionService = Depends(lambda: topic_interaction_service),
):
    """
    Scores submissions, computes mastery delta deterministically, records attempts,
    and returns granular feedback.
    """
    return await service.submit_topic_answers(
        user_id=current_user.user_id,
        topic_id=topic_id,
        submission=request,
    )


@router.post(
    "/{topic_id}/ask",
    response_model=ContextualAskResponse,
    summary="Ask Question: Topic-Scoped Socratic Q&A (RAG-backed)",
)
async def ask_topic_question(
    topic_id: str,
    request: ContextualAskRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: TopicInteractionService = Depends(lambda: topic_interaction_service),
):
    """
    Answers freeform learner questions scoped to the current topic and grounded
    in uploaded RAG knowledge documents.
    """
    return await service.ask_topic_question(
        user_id=current_user.user_id,
        topic_id=topic_id,
        query=request.query,
    )
