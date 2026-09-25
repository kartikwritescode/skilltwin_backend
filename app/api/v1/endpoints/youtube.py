from fastapi import APIRouter, Depends, status, Query
from typing import Optional, List
from datetime import date

from app.core.security import CurrentUser, get_current_user
from app.schemas.youtube import (
    YouTubePlaylistImportRequest,
    YouTubeVideoProgressUpdateRequest,
    YouTubeScheduleRecalculateRequest,
    YouTubeVideoResponse,
    YouTubePlaylistResponse,
    YouTubePlaylistRefreshResponse,
    PersonalizedScheduleResponse,
)
from app.services.youtube_service import YouTubeService, youtube_service

router = APIRouter(prefix="/youtube", tags=["YouTube Playlist Roadmaps"])


@router.post(
    "/playlists/import",
    response_model=YouTubePlaylistResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Import YouTube Playlist to Personalized Roadmap",
)
async def import_youtube_playlist(
    request: YouTubePlaylistImportRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: YouTubeService = Depends(lambda: youtube_service),
):
    """
    Takes a YouTube playlist URL, fetches all video metadata via YouTube Data API v3,
    preserves creator's exact sequential order, checks cache/content hash,
    enhances with batched Gemini topic analysis, and links seamlessly into
    SkillTwin's personalized roadmap engine.
    """
    return await service.import_playlist(
        user_id=current_user.user_id,
        request=request,
    )


@router.get(
    "/playlists/{playlist_id}",
    response_model=YouTubePlaylistResponse,
    summary="Get YouTube Playlist Roadmap & Progress",
)
async def get_youtube_playlist(
    playlist_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    service: YouTubeService = Depends(lambda: youtube_service),
):
    """
    Returns full roadmap, module groupings, active resume point,
    and personalized completion schedule.
    """
    return await service.get_playlist_response(
        playlist_id=playlist_id,
        user_id=current_user.user_id,
    )


@router.get(
    "/playlists/{playlist_id}/videos",
    response_model=List[YouTubeVideoResponse],
    summary="Get All Playlist Videos in Sequential Order",
)
async def get_playlist_videos(
    playlist_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    service: YouTubeService = Depends(lambda: youtube_service),
):
    """
    Returns all videos for the playlist strictly sorted by position ascending.
    Authoritative creator order is preserved.
    """
    resp = await service.get_playlist_response(playlist_id=playlist_id, user_id=current_user.user_id)
    videos = []
    for mod in resp.modules:
        videos.extend(mod.videos)
    return videos


@router.post(
    "/playlists/{playlist_id}/refresh",
    response_model=YouTubePlaylistRefreshResponse,
    summary="Sync & Detect Changes from YouTube Playlist",
)
async def refresh_youtube_playlist(
    playlist_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    service: YouTubeService = Depends(lambda: youtube_service),
):
    """
    Detects added, deleted, or reordered videos.
    Only new videos are sent to Gemini (incremental cost optimization).
    Preserves learner's completed video history.
    """
    return await service.refresh_playlist(
        playlist_id=playlist_id,
        user_id=current_user.user_id,
    )


@router.patch(
    "/videos/{video_id}/progress",
    response_model=YouTubeVideoResponse,
    summary="Update Video Completion Progress",
)
async def update_video_progress(
    video_id: str,
    request: YouTubeVideoProgressUpdateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: YouTubeService = Depends(lambda: youtube_service),
):
    """
    Updates completion state (NOT_STARTED, IN_PROGRESS, COMPLETED, SKIPPED).
    In strict playlist mode, completing Video N unlocks Video N+1.
    Cascades to linked SkillTwin LearningPath topic progress.
    """
    return await service.update_video_progress(
        video_id=video_id,
        user_id=current_user.user_id,
        request=request,
    )


@router.post(
    "/playlists/{playlist_id}/schedule",
    response_model=PersonalizedScheduleResponse,
    summary="Recalculate Personalized Schedule on Pace Change",
)
async def recalculate_schedule(
    playlist_id: str,
    request: YouTubeScheduleRecalculateRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: YouTubeService = Depends(lambda: youtube_service),
):
    """
    Dynamically recalculates daily study queue and completion target
    without changing the underlying authoritative video sequence.
    """
    videos_db = await service.repo.get_playlist_videos(playlist_id)
    sched = service.calculate_personalized_schedule(
        videos=[{
            "id": v.id,
            "position": v.position,
            "youtube_video_id": v.youtube_video_id,
            "title": v.title,
            "duration_seconds": v.duration_seconds,
            "youtube_url": v.youtube_url,
            "status": v.status,
        } for v in videos_db],
        daily_minutes=request.daily_minutes,
        pace=request.pace,
        revision_frequency=request.revision_frequency,
        deadline=request.deadline,
    )
    return PersonalizedScheduleResponse(
        total_videos=sched["total_videos"],
        total_duration_hours=sched["total_duration_hours"],
        daily_minutes=sched["daily_minutes"],
        days_per_week=sched.get("days_per_week", 5),
        estimated_weeks=sched["estimated_weeks"],
        estimated_completion_date=sched.get("estimated_completion_date"),
        schedule_days=sched.get("schedule_days", []),
    )
