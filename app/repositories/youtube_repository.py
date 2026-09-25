import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from sqlalchemy import select, update, delete, and_, desc, cast, String, text
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import AsyncSessionLocal
from app.core.db_models import (
    YouTubePlaylistModel,
    YouTubePlaylistVideoModel,
    YouTubePlaylistCacheModel,
)
from app.core.logging import logger


class YouTubeRepository:
    """
    Data access layer for YouTube playlist curriculums, video nodes,
    content caching, and learner progress.
    """

    async def _ensure_profile_exists(self, session: AsyncSession, user_id: Any) -> None:
        if not user_id:
            return
        try:
            async with session.begin_nested():
                await session.execute(
                    text("INSERT INTO profiles (id, display_name) VALUES (:id, 'Learner') ON CONFLICT (id) DO NOTHING"),
                    {"id": str(user_id)}
                )
        except Exception as e:
            logger.warning(f"Could not auto-ensure profile for user {user_id}: {e}")

    # ---------------------------------------------------------------------------
    # Playlist Cache (Shared across all users)
    # ---------------------------------------------------------------------------

    async def get_cache(self, youtube_playlist_id: str, content_hash: str) -> Optional[YouTubePlaylistCacheModel]:
        async with AsyncSessionLocal() as session:
            stmt = select(YouTubePlaylistCacheModel).where(
                and_(
                    YouTubePlaylistCacheModel.youtube_playlist_id == youtube_playlist_id,
                    YouTubePlaylistCacheModel.content_hash == content_hash,
                )
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def save_cache(self, cache: YouTubePlaylistCacheModel) -> YouTubePlaylistCacheModel:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                existing = await session.get(YouTubePlaylistCacheModel, cache.id)
                if existing:
                    existing.title = cache.title
                    existing.description = cache.description
                    existing.channel_name = cache.channel_name
                    existing.thumbnail_url = cache.thumbnail_url
                    existing.video_count = cache.video_count
                    existing.total_duration_seconds = cache.total_duration_seconds
                    existing.cached_videos = cache.cached_videos
                    existing.topic_groups = cache.topic_groups
                    existing.analysis_version = cache.analysis_version
                    existing.updated_at = datetime.now(timezone.utc)
                    return existing
                else:
                    session.add(cache)
                    await session.flush()
                    return cache

    # ---------------------------------------------------------------------------
    # User YouTube Playlists
    # ---------------------------------------------------------------------------

    async def save_playlist(self, playlist: YouTubePlaylistModel) -> YouTubePlaylistModel:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                await self._ensure_profile_exists(session, playlist.user_id)
                existing = await session.get(YouTubePlaylistModel, playlist.id)
                if existing:
                    existing.title = playlist.title
                    existing.description = playlist.description
                    existing.channel_name = playlist.channel_name
                    existing.thumbnail_url = playlist.thumbnail_url
                    existing.video_count = playlist.video_count
                    existing.total_duration_seconds = playlist.total_duration_seconds
                    existing.content_hash = playlist.content_hash
                    existing.analysis_status = playlist.analysis_status
                    existing.analysis_version = playlist.analysis_version
                    existing.learning_path_id = playlist.learning_path_id
                    existing.metadata_json = playlist.metadata_json
                    existing.updated_at = datetime.now(timezone.utc)
                    return existing
                else:
                    session.add(playlist)
                    await session.flush()
                    return playlist

    async def get_playlist(self, playlist_id: str, user_id: Optional[str] = None) -> Optional[YouTubePlaylistModel]:
        async with AsyncSessionLocal() as session:
            filters = [cast(YouTubePlaylistModel.id, String) == str(playlist_id)]
            if user_id:
                filters.append(cast(YouTubePlaylistModel.user_id, String) == str(user_id))
            stmt = select(YouTubePlaylistModel).where(and_(*filters))
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_playlist_by_yt_id(self, youtube_playlist_id: str, user_id: str) -> Optional[YouTubePlaylistModel]:
        async with AsyncSessionLocal() as session:
            stmt = select(YouTubePlaylistModel).where(
                and_(
                    YouTubePlaylistModel.youtube_playlist_id == youtube_playlist_id,
                    cast(YouTubePlaylistModel.user_id, String) == str(user_id),
                )
            ).order_by(desc(YouTubePlaylistModel.created_at))
            result = await session.execute(stmt)
            return result.scalars().first()

    async def get_user_playlists(self, user_id: str) -> List[YouTubePlaylistModel]:
        async with AsyncSessionLocal() as session:
            stmt = select(YouTubePlaylistModel).where(
                cast(YouTubePlaylistModel.user_id, String) == str(user_id)
            ).order_by(desc(YouTubePlaylistModel.created_at))
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def delete_playlist(self, playlist_id: str, user_id: str) -> bool:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                stmt = delete(YouTubePlaylistModel).where(
                    and_(
                        cast(YouTubePlaylistModel.id, String) == str(playlist_id),
                        cast(YouTubePlaylistModel.user_id, String) == str(user_id),
                    )
                )
                res = await session.execute(stmt)
                return res.rowcount > 0

    # ---------------------------------------------------------------------------
    # Playlist Videos (Preserves Exact Sequential Position)
    # ---------------------------------------------------------------------------

    async def save_videos(self, videos: List[YouTubePlaylistVideoModel]) -> List[YouTubePlaylistVideoModel]:
        if not videos:
            return []
        async with AsyncSessionLocal() as session:
            async with session.begin():
                for v in videos:
                    # Check if video already exists by playlist_id + youtube_video_id
                    stmt = select(YouTubePlaylistVideoModel).where(
                        and_(
                            cast(YouTubePlaylistVideoModel.playlist_id, String) == str(v.playlist_id),
                            YouTubePlaylistVideoModel.youtube_video_id == v.youtube_video_id,
                        )
                    )
                    existing = (await session.execute(stmt)).scalar_one_or_none()
                    if existing:
                        existing.position = v.position
                        existing.title = v.title
                        existing.description = v.description
                        existing.duration_seconds = v.duration_seconds
                        existing.thumbnail_url = v.thumbnail_url
                        existing.youtube_url = v.youtube_url
                        existing.topic = v.topic
                        existing.subtopics = v.subtopics
                        existing.difficulty = v.difficulty
                        existing.concepts = v.concepts
                        existing.prerequisite_positions = v.prerequisite_positions
                        existing.availability = v.availability
                        existing.metadata_json = v.metadata_json
                        existing.updated_at = datetime.now(timezone.utc)
                    else:
                        session.add(v)
                await session.flush()
                return videos

    async def get_playlist_videos(self, playlist_id: str) -> List[YouTubePlaylistVideoModel]:
        """
        Returns all videos for a playlist strictly ordered by position ascending.
        Authoritative YouTube order is preserved.
        """
        async with AsyncSessionLocal() as session:
            stmt = select(YouTubePlaylistVideoModel).where(
                cast(YouTubePlaylistVideoModel.playlist_id, String) == str(playlist_id)
            ).order_by(YouTubePlaylistVideoModel.position.asc())
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_video(self, video_id: str) -> Optional[YouTubePlaylistVideoModel]:
        async with AsyncSessionLocal() as session:
            stmt = select(YouTubePlaylistVideoModel).where(
                cast(YouTubePlaylistVideoModel.id, String) == str(video_id)
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def update_video_progress(
        self,
        video_id: str,
        status: str,
        watch_progress: float = 0.0,
        notes: Optional[str] = None,
        user_rating: Optional[float] = None,
    ) -> Optional[YouTubePlaylistVideoModel]:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                video = await session.get(YouTubePlaylistVideoModel, video_id)
                if not video:
                    # Try by string cast
                    stmt = select(YouTubePlaylistVideoModel).where(
                        cast(YouTubePlaylistVideoModel.id, String) == str(video_id)
                    )
                    video = (await session.execute(stmt)).scalar_one_or_none()
                if not video:
                    return None

                video.status = status.upper()
                video.watch_progress = max(0.0, min(1.0, float(watch_progress)))
                if notes is not None:
                    video.notes = notes
                if user_rating is not None:
                    video.user_rating = float(user_rating)

                now = datetime.now(timezone.utc)
                if video.status == "IN_PROGRESS" and not video.started_at:
                    video.started_at = now
                elif video.status == "COMPLETED":
                    if not video.started_at:
                        video.started_at = now
                    video.completed_at = now
                    video.watch_progress = 1.0

                video.updated_at = now
                await session.flush()
                return video


youtube_repo = YouTubeRepository()
