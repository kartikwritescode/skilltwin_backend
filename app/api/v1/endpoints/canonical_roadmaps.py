from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from app.services.canonical_roadmap_service import canonical_roadmap_service
from app.services.ai_roadmap_generator import ai_roadmap_generator

router = APIRouter(prefix="/roadmaps/canonical", tags=["Canonical Roadmaps"])


class CanonicalRoadmapSummary(BaseModel):
    id: str
    slug: str
    title: str
    description: str
    domain: str
    target_role: Optional[str] = None
    difficulty_baseline: str
    tags: List[str]
    total_nodes: int
    estimated_hours: float


class CanonicalNodeDetail(BaseModel):
    id: str
    concept_id: str
    title: str
    subtitle: Optional[str] = None
    phase: str
    tier: str
    importance: str = "essential"
    difficulty: str = "intermediate"
    order: int
    estimated_minutes: int
    prerequisites: List[str]
    learning_objectives: List[str]
    feynman_prompts: List[str]
    key_misconceptions: List[str]


class CanonicalRoadmapDetail(CanonicalRoadmapSummary):
    nodes: List[CanonicalNodeDetail]


class MatchRequest(BaseModel):
    goal_title: str
    goal_description: Optional[str] = None
    target_benchmark: Optional[str] = None
    threshold: float = 0.70


class MatchResponse(BaseModel):
    matched: bool
    similarity_score: Optional[float] = None
    roadmap: Optional[CanonicalRoadmapSummary] = None


@router.get("", response_model=List[CanonicalRoadmapSummary])
async def list_canonical_roadmaps():
    """List all available canonical technology roadmaps."""
    await canonical_roadmap_service.ensure_fixtures_loaded()
    roadmaps = await canonical_roadmap_service.canonical_repo.list_all(active_only=True)
    return [
        CanonicalRoadmapSummary(
            id=r.id,
            slug=r.slug,
            title=r.title,
            description=r.description,
            domain=r.domain,
            target_role=r.target_role,
            difficulty_baseline=r.difficulty_baseline,
            tags=r.tags or [],
            total_nodes=r.total_nodes,
            estimated_hours=r.estimated_hours,
        )
        for r in roadmaps
    ]


@router.get("/{slug_or_id}", response_model=CanonicalRoadmapDetail)
async def get_canonical_roadmap(slug_or_id: str):
    """Retrieve full curriculum details for a specific canonical roadmap by ID or slug."""
    await canonical_roadmap_service.ensure_fixtures_loaded()
    roadmap = await canonical_roadmap_service.canonical_repo.get_by_id(slug_or_id)
    if not roadmap:
        roadmap = await canonical_roadmap_service.canonical_repo.get_by_slug(slug_or_id)

    if not roadmap:
        raise HTTPException(status_code=404, detail=f"Canonical roadmap '{slug_or_id}' not found.")

    nodes_detail = [
        CanonicalNodeDetail(
            id=n.id,
            concept_id=n.concept_id,
            title=n.title,
            subtitle=n.subtitle,
            phase=n.phase,
            tier=n.tier,
            order=n.order,
            estimated_minutes=n.estimated_minutes,
            prerequisites=n.prerequisites or [],
            learning_objectives=n.learning_objectives or [],
            feynman_prompts=n.feynman_prompts or [],
            key_misconceptions=n.key_misconceptions or [],
        )
        for n in sorted(roadmap.nodes, key=lambda x: x.order)
    ]

    return CanonicalRoadmapDetail(
        id=roadmap.id,
        slug=roadmap.slug,
        title=roadmap.title,
        description=roadmap.description,
        domain=roadmap.domain,
        target_role=roadmap.target_role,
        difficulty_baseline=roadmap.difficulty_baseline,
        tags=roadmap.tags or [],
        total_nodes=roadmap.total_nodes,
        estimated_hours=roadmap.estimated_hours,
        nodes=nodes_detail,
    )


@router.post("/match", response_model=MatchResponse)
async def match_roadmap(request: MatchRequest):
    """Test vector similarity matching for a given learning goal."""
    match = await canonical_roadmap_service.find_matching_roadmap(
        goal_title=request.goal_title,
        goal_description=request.goal_description,
        target_benchmark=request.target_benchmark,
        threshold=request.threshold,
    )

    if not match:
        return MatchResponse(matched=False)

    roadmap, score = match
    return MatchResponse(
        matched=True,
        similarity_score=round(score, 3),
        roadmap=CanonicalRoadmapSummary(
            id=roadmap.id,
            slug=roadmap.slug,
            title=roadmap.title,
            description=roadmap.description,
            domain=roadmap.domain,
            target_role=roadmap.target_role,
            difficulty_baseline=roadmap.difficulty_baseline,
            tags=roadmap.tags or [],
            total_nodes=roadmap.total_nodes,
            estimated_hours=roadmap.estimated_hours,
        ),
    )


# ============================================================================
# AI-POWERED ROADMAP GENERATION ENDPOINTS
# ============================================================================


class GenerateRoadmapRequest(BaseModel):
    """Request to generate a new AI-powered roadmap."""
    domain: str = Field(..., description="Learning domain (e.g., 'Frontend Development', 'Data Science')")
    target_role: str = Field(..., description="Target job role (e.g., 'Senior Frontend Engineer')")
    difficulty_baseline: str = Field(default="Beginner", description="Starting difficulty level")
    tags: Optional[List[str]] = Field(default=None, description="Relevant tags/keywords")
    user_goals: Optional[str] = Field(default=None, description="Specific user goals or context")
    specializations: Optional[List[str]] = Field(default=None, description="Areas to emphasize")
    temperature: float = Field(default=0.7, ge=0.0, le=1.0, description="AI creativity (0.0-1.0)")


class GenerateRoadmapResponse(BaseModel):
    """Response containing the generated roadmap."""
    success: bool
    roadmap: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    node_count: Optional[int] = None


class RefineRoadmapRequest(BaseModel):
    """Request to refine an existing roadmap."""
    roadmap: Dict[str, Any] = Field(..., description="The existing roadmap JSON")
    refinement_instructions: str = Field(..., description="What to change or improve")
    temperature: float = Field(default=0.6, ge=0.0, le=1.0, description="AI creativity")


@router.post("/generate", response_model=GenerateRoadmapResponse)
async def generate_ai_roadmap(request: GenerateRoadmapRequest):
    """
    Generate a personalized roadmap using AI based on user inputs.
    Uses static roadmap templates as reference to ensure quality and structure.
    """
    try:
        roadmap_data = await ai_roadmap_generator.generate_roadmap(
            domain=request.domain,
            target_role=request.target_role,
            difficulty_baseline=request.difficulty_baseline,
            tags=request.tags,
            user_goals=request.user_goals,
            specializations=request.specializations,
            temperature=request.temperature,
        )

        return GenerateRoadmapResponse(
            success=True,
            roadmap=roadmap_data,
            node_count=len(roadmap_data.get("nodes", [])),
        )

    except ValueError as e:
        return GenerateRoadmapResponse(
            success=False,
            error=f"Validation error: {str(e)}",
        )
    except Exception as e:
        return GenerateRoadmapResponse(
            success=False,
            error=f"Generation failed: {str(e)}",
        )


@router.post("/refine", response_model=GenerateRoadmapResponse)
async def refine_roadmap(request: RefineRoadmapRequest):
    """
    Refine an existing roadmap based on user feedback or instructions.
    Maintains structure while applying requested changes.
    """
    try:
        refined_roadmap = await ai_roadmap_generator.refine_existing_roadmap(
            existing_roadmap=request.roadmap,
            refinement_instructions=request.refinement_instructions,
            temperature=request.temperature,
        )

        return GenerateRoadmapResponse(
            success=True,
            roadmap=refined_roadmap,
            node_count=len(refined_roadmap.get("nodes", [])),
        )

    except ValueError as e:
        return GenerateRoadmapResponse(
            success=False,
            error=f"Validation error: {str(e)}",
        )
    except Exception as e:
        return GenerateRoadmapResponse(
            success=False,
            error=f"Refinement failed: {str(e)}",
        )
