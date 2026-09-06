from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from typing import Optional
from app.schemas.journeys import JourneyResponse, JourneyNodeResponse, JourneyNodeUpdate
from app.services.journey_service import JourneyService, journey_service
from app.core.security import CurrentUser, get_current_user

router = APIRouter(prefix="/journeys", tags=["Journeys"])


class RemediationInsertRequest(BaseModel):
    target_node_id: str
    concept_id: str
    title: str
    subtitle: str
    estimated_minutes: int = 15


@router.get("/{journey_id}", response_model=JourneyResponse, summary="Get Journey Roadmap")
async def get_journey(
    journey_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    service: JourneyService = Depends(lambda: journey_service),
):
    """
    Returns the complete structured winding roadmap including nodes,
    order, phases, states (LOCKED, AVAILABLE, CURRENT, COMPLETED, SKIPPED),
    prerequisites, and calculated overall progress.
    """
    return await service.get_journey(journey_id=journey_id)


@router.patch("/{journey_id}/nodes/{node_id}", response_model=JourneyResponse, summary="Update Journey Node State")
async def update_node_state(
    journey_id: str,
    node_id: str,
    update: JourneyNodeUpdate,
    current_user: CurrentUser = Depends(get_current_user),
    service: JourneyService = Depends(lambda: journey_service),
):
    """
    Updates the state of a specific node (e.g. COMPLETED, CURRENT).
    Triggers prerequisite cascade unlocking downstream and recalculates overall journey progress.
    """
    if update.state is None:
        return await service.get_journey(journey_id=journey_id)
    journey = await service.update_node_state(
        journey_id=journey_id,
        node_id=node_id,
        new_state=update.state,
        node_progress=update.progress,
    )
    return await service.get_journey(journey_id=journey.id)


@router.post("/{journey_id}/remediation", response_model=JourneyNodeResponse, status_code=status.HTTP_201_CREATED, summary="Insert Remediation Node")
async def insert_remediation(
    journey_id: str,
    request: RemediationInsertRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: JourneyService = Depends(lambda: journey_service),
):
    """
    Dynamically inserts a remediation node before a target node when a knowledge gap is identified.
    """
    node = await service.insert_remediation_nodes(
        journey_id=journey_id,
        target_node_id=request.target_node_id,
        concept_id=request.concept_id,
        title=request.title,
        subtitle=request.subtitle,
        estimated_minutes=request.estimated_minutes,
    )
    return JourneyNodeResponse(
        id=node.id,
        title=node.title,
        subtitle=node.subtitle,
        phase=node.phase,
        state=node.state,
        progress=node.progress,
        concept_id=node.concept_id,
        estimated_minutes=node.estimated_minutes,
        prerequisites=node.prerequisites,
        is_remediation=node.is_remediation,
        order=node.order,
        position_x=node.position_x,
        position_y=node.position_y,
    )
