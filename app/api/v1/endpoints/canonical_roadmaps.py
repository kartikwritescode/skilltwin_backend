from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from app.services.canonical_roadmap_service import canonical_roadmap_service

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
