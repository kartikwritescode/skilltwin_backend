from fastapi import APIRouter
from app.api.v1.endpoints import (
    auth,
    health,
    profile,
    twin,
    goals,
    journeys,
    mentor,
    sessions,
    concepts,
    revision,
    resources,
    knowledge,
    teach,
)

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(health.router)
api_router.include_router(profile.router)
api_router.include_router(twin.router)
api_router.include_router(goals.router)
api_router.include_router(journeys.router)
api_router.include_router(mentor.router)
api_router.include_router(sessions.router)
api_router.include_router(concepts.router)
api_router.include_router(revision.router)
api_router.include_router(resources.router)
api_router.include_router(knowledge.router)
api_router.include_router(teach.router)
