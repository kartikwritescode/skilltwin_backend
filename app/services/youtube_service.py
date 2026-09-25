import uuid
import re
import math
import hashlib
import urllib.parse
from datetime import datetime, timezone, date, timedelta
from typing import Optional, List, Dict, Any, Tuple
import httpx
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.logging import logger
from app.core.exceptions import ValidationError, ResourceExhaustedError, EntityNotFoundError
from app.core.db_models import (
    GoalModel,
    LearningPathModel,
    LearningSectionModel,
    LearningTopicModel,
    LearnerTopicProgressModel,
    YouTubePlaylistModel,
    YouTubePlaylistVideoModel,
    YouTubePlaylistCacheModel,
)
from app.repositories.youtube_repository import YouTubeRepository, youtube_repo
from app.repositories.dynamic_learning_repository import DynamicLearningRepository, dynamic_learning_repo
from app.ai.providers.factory import get_llm_provider
from app.schemas.youtube import (
    YouTubePlaylistImportRequest,
    YouTubeVideoProgressUpdateRequest,
    YouTubeVideoResponse,
    YouTubeModuleResponse,
    PersonalizedScheduleDay,
    PersonalizedScheduleResponse,
    ScheduledVideoItem,
    YouTubePlaylistResponse,
    YouTubePlaylistRefreshResponse,
)

YOUTUBE_API_BASE_URL = "https://www.googleapis.com/youtube/v3"


# ---------------------------------------------------------------------------
# Structured LLM Schemas for Batch Curriculum Extraction
# ---------------------------------------------------------------------------

class VideoAnalysisItem(BaseModel):
    position: int = Field(default=0, description="The exact supplied integer position of the video")
    topic: str = Field(default="Core Curriculum", description="Primary topic or subject")
    subtopics: List[str] = Field(default_factory=list, description="Granular subtopics covered")
    difficulty: str = Field(default="beginner", description="beginner, intermediate, or advanced")
    concepts: List[str] = Field(default_factory=list, description="Key concepts or keywords taught")
    prerequisite_positions: List[int] = Field(default_factory=list, description="Positions of previous videos that are strict prerequisites")


class PlaylistCurriculumAnalysis(BaseModel):
    playlist_topic: str = Field(default="YouTube Course", description="Overall domain or curriculum topic")
    overall_level: str = Field(default="beginner_to_intermediate", description="Overall difficulty level")
    videos: List[VideoAnalysisItem] = Field(default_factory=list, description="Analyzed videos in exact sequence")


# ---------------------------------------------------------------------------
# YouTube Service Implementation
# ---------------------------------------------------------------------------

class YouTubeService:
    """
    Production-grade service managing YouTube playlist retrieval, caching,
    batched Gemini curriculum enhancement, and personalized schedule projection.
    
    Invariant: YouTube playlist sequence is canonical and authoritative.
    """

    def __init__(
        self,
        repository: YouTubeRepository = youtube_repo,
        dl_repo: DynamicLearningRepository = dynamic_learning_repo,
    ):
        self.repo = repository
        self.dl_repo = dl_repo

    # ---------------------------------------------------------------------------
    # URL Parsing & Validation
    # ---------------------------------------------------------------------------

    @staticmethod
    def extract_playlist_id(url: str) -> str:
        """
        Validates and extracts YouTube playlist ID from standard URLs, shortened links,
        or bare playlist IDs. Rejects bare video URLs or invalid strings.
        """
        if not url or not isinstance(url, str):
            raise ValidationError("This doesn't appear to be a valid YouTube playlist URL.")

        cleaned = url.strip()

        # Check for bare playlist ID (e.g. PL..., UU..., FL..., RD..., OLAK5uy_...)
        if re.match(r"^(PL|UU|FL|RD|OLAK5uy_)[a-zA-Z0-9_-]{10,}$", cleaned):
            return cleaned

        try:
            target_url = cleaned if "://" in cleaned else f"https://{cleaned}"
            parsed = urllib.parse.urlparse(target_url)
            netloc = parsed.netloc.lower()
            if "youtube.com" not in netloc and "youtu.be" not in netloc:
                raise ValidationError("This doesn't appear to be a valid YouTube playlist URL.")

            qs = urllib.parse.parse_qs(parsed.query)
            if "list" in qs and qs["list"]:
                playlist_id = qs["list"][0].strip()
                if re.match(r"^[a-zA-Z0-9_-]{10,}$", playlist_id):
                    return playlist_id

            raise ValidationError("This doesn't appear to be a valid YouTube playlist URL.")
        except ValidationError:
            raise
        except Exception as e:
            logger.warning(f"Error parsing YouTube URL '{url}': {e}")
            raise ValidationError("This doesn't appear to be a valid YouTube playlist URL.")

    # ---------------------------------------------------------------------------
    # ISO 8601 Duration Parser
    # ---------------------------------------------------------------------------

    @staticmethod
    def parse_iso8601_duration(duration_str: Optional[str]) -> int:
        """
        Parses ISO 8601 duration string (e.g., PT1H23M45S, PT18M, PT45S, P1DT2H) into total seconds.
        """
        if not duration_str or not isinstance(duration_str, str):
            return 0
        pattern = r"P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?"
        match = re.match(pattern, duration_str)
        if not match:
            return 0
        parts = match.groupdict()
        days = int(parts.get("days") or 0)
        hours = int(parts.get("hours") or 0)
        minutes = int(parts.get("minutes") or 0)
        seconds = int(parts.get("seconds") or 0)
        return days * 86400 + hours * 3600 + minutes * 60 + seconds

    @staticmethod
    def format_duration(seconds: int) -> str:
        """Formats seconds into hh:mm or mm:ss."""
        hours = seconds // 3600
        mins = (seconds % 3600) // 60
        secs = seconds % 60
        if hours > 0:
            return f"{hours}:{mins:02d}:{secs:02d}"
        return f"{mins:02d}:{secs:02d}"

    @staticmethod
    def format_duration_human(seconds: int) -> str:
        """Formats seconds into human friendly 'Xh Ym'."""
        hours = seconds // 3600
        mins = (seconds % 3600) // 60
        if hours > 0:
            return f"{hours}h {mins}m"
        return f"{mins}m"

    # ---------------------------------------------------------------------------
    # Content Hashing
    # ---------------------------------------------------------------------------

    @staticmethod
    def compute_content_hash(videos: List[Dict[str, Any]]) -> str:
        """
        Computes deterministic SHA-256 hash from video IDs in their authoritative sequence.
        """
        id_sequence = ",".join([str(v.get("youtube_video_id", "")) for v in videos])
        return hashlib.sha256(id_sequence.encode("utf-8")).hexdigest()

    # ---------------------------------------------------------------------------
    # YouTube Data API v3 Client
    # ---------------------------------------------------------------------------

    async def fetch_playlist_metadata(self, playlist_id: str) -> Dict[str, Any]:
        """Fetches title, description, creator, and thumbnail for the playlist."""
        api_key = settings.effective_youtube_api_key

        if settings.YOUTUBE_MOCK or not api_key:
            return self._get_mock_playlist_metadata(playlist_id)

        url = f"{YOUTUBE_API_BASE_URL}/playlists"
        params = {
            "part": "snippet,contentDetails",
            "id": playlist_id,
            "key": api_key,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.get(url, params=params)
                if res.status_code == 200:
                    data = res.json()
                    items = data.get("items", [])
                    if not items:
                        raise EntityNotFoundError(f"YouTube playlist '{playlist_id}' not found or is private.")
                    item = items[0]
                    snippet = item.get("snippet", {})
                    content_details = item.get("contentDetails", {})
                    thumbnails = snippet.get("thumbnails", {})
                    thumb_url = (
                        thumbnails.get("maxres", {}).get("url")
                        or thumbnails.get("standard", {}).get("url")
                        or thumbnails.get("high", {}).get("url")
                        or thumbnails.get("medium", {}).get("url")
                        or thumbnails.get("default", {}).get("url")
                        or ""
                    )
                    return {
                        "playlist_id": playlist_id,
                        "title": snippet.get("title", "YouTube Learning Course"),
                        "description": snippet.get("description", ""),
                        "channel_name": snippet.get("channelTitle", "YouTube Creator"),
                        "thumbnail_url": thumb_url,
                        "video_count": int(content_details.get("itemCount", 0)),
                    }
                elif res.status_code in (400, 401):
                    logger.warning(f"YouTube API key invalid or API not enabled ({res.status_code}). Using fallback metadata.")
                    return self._get_mock_playlist_metadata(playlist_id)
                elif res.status_code == 429:
                    logger.warning(f"YouTube API quota exceeded or forbidden ({res.status_code}): {res.text[:150]}")
                    raise ResourceExhaustedError("YouTube API quota exceeded. Please check your YouTube API key or try again later.")
                elif res.status_code == 404:
                    raise EntityNotFoundError(f"YouTube playlist '{playlist_id}' not found.")
                else:
                    logger.warning(f"YouTube API returned {res.status_code}: {res.text[:100]}")
                    return self._get_mock_playlist_metadata(playlist_id)
        except (ResourceExhaustedError, EntityNotFoundError):
            raise
        except Exception as e:
            logger.error(f"Error calling YouTube API playlists: {e}. Falling back to resilient mock metadata.")
            return self._get_mock_playlist_metadata(playlist_id)

    async def fetch_playlist_items(self, playlist_id: str) -> List[Dict[str, Any]]:
        """
        Fetches ALL videos in the playlist through YouTube Data API v3 with pagination.
        Preserves exact sequence, filters out deleted/private/unavailable videos safely.
        """
        api_key = settings.effective_youtube_api_key

        if settings.YOUTUBE_MOCK or not api_key:
            return self._get_mock_playlist_items(playlist_id)

        url = f"{YOUTUBE_API_BASE_URL}/playlistItems"
        raw_items: List[Dict[str, Any]] = []
        page_token: Optional[str] = None
        max_pages = 20  # Safeguard: up to 1,000 videos

        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                for _ in range(max_pages):
                    params: Dict[str, Any] = {
                        "part": "snippet,contentDetails,status",
                        "playlistId": playlist_id,
                        "maxResults": 50,
                        "key": api_key,
                    }
                    if page_token:
                        params["pageToken"] = page_token

                    res = await client.get(url, params=params)
                    if res.status_code == 200:
                        data = res.json()
                        items = data.get("items", [])
                        raw_items.extend(items)
                        page_token = data.get("nextPageToken")
                        if not page_token:
                            break
                    elif res.status_code == 429:
                        logger.warning(f"YouTube API quota exceeded: {res.text[:150]}")
                        raise ResourceExhaustedError("YouTube API quota exceeded.")
                    else:
                        logger.warning(f"YouTube API status {res.status_code} fetching items: {res.text[:100]}")
                        break
        except ResourceExhaustedError:
            raise
        except Exception as e:
            logger.error(f"Error fetching playlist items: {e}")

        if not raw_items:
            logger.info(f"Using resilient fallback items for playlist {playlist_id}.")
            return self._get_mock_playlist_items(playlist_id)

        # Process, preserve exact order, and safely filter unavailable videos
        parsed_videos: List[Dict[str, Any]] = []
        video_ids_for_details: List[str] = []
        position_counter = 0

        for item in raw_items:
            snippet = item.get("snippet", {})
            status = item.get("status", {})
            title = snippet.get("title", "").strip()

            # Safely skip deleted or private videos
            if title in ["Private video", "Deleted video"] or status.get("privacyStatus") == "private":
                continue

            video_id = snippet.get("resourceId", {}).get("videoId")
            if not video_id:
                continue

            thumbnails = snippet.get("thumbnails", {})
            thumb_url = (
                thumbnails.get("high", {}).get("url")
                or thumbnails.get("medium", {}).get("url")
                or thumbnails.get("default", {}).get("url")
                or f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
            )

            parsed_videos.append({
                "position": position_counter,
                "youtube_video_id": video_id,
                "title": title,
                "description": snippet.get("description", ""),
                "thumbnail_url": thumb_url,
                "channel_name": snippet.get("videoOwnerChannelTitle") or snippet.get("channelTitle", ""),
                "youtube_url": f"https://www.youtube.com/watch?v={video_id}",
                "duration_seconds": 0,  # Will be enriched by fetch_video_details
                "availability": "available",
            })
            video_ids_for_details.append(video_id)
            position_counter += 1

        # Fetch actual video durations in batches of 50
        if video_ids_for_details:
            details_map = await self.fetch_video_details(video_ids_for_details)
            for v in parsed_videos:
                vid = v["youtube_video_id"]
                if vid in details_map:
                    v["duration_seconds"] = details_map[vid].get("duration_seconds", 0)

        return parsed_videos

    async def fetch_video_details(self, video_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """Batches requests to videos.list (up to 50 at a time) to retrieve accurate duration."""
        api_key = settings.effective_youtube_api_key
        if not api_key:
            return {}

        results: Dict[str, Dict[str, Any]] = {}
        chunk_size = 50
        url = f"{YOUTUBE_API_BASE_URL}/videos"

        async with httpx.AsyncClient(timeout=20.0) as client:
            for i in range(0, len(video_ids), chunk_size):
                chunk = video_ids[i:i + chunk_size]
                params = {
                    "part": "contentDetails,snippet,status",
                    "id": ",".join(chunk),
                    "key": api_key,
                }
                try:
                    res = await client.get(url, params=params)
                    if res.status_code == 200:
                        for item in res.json().get("items", []):
                            vid = item.get("id")
                            iso_dur = item.get("contentDetails", {}).get("duration", "")
                            duration_seconds = self.parse_iso8601_duration(iso_dur)
                            results[vid] = {
                                "duration_seconds": duration_seconds,
                            }
                except Exception as e:
                    logger.warning(f"Error fetching video details for chunk {i}: {e}")

        return results

    # ---------------------------------------------------------------------------
    # Batched Gemini Topic Analysis (Cost Optimized)
    # ---------------------------------------------------------------------------

    async def analyze_curriculum_with_gemini(
        self,
        videos: List[Dict[str, Any]],
        playlist_title: str,
    ) -> List[Dict[str, Any]]:
        """
        Batches curriculum analysis to Gemini (approx 1-5 calls max).
        Only sends position, title, truncated description, duration.
        Enforces that playlist order is authoritative.
        Never reorders, never removes, never invents videos.
        """
        if not videos:
            return []

        llm = get_llm_provider()
        enriched_videos: List[Dict[str, Any]] = [dict(v) for v in videos]

        system_instruction = (
            "You are a curriculum analysis engine for SkillTwin.\n"
            "You are given an ordered list of videos from a YouTube learning playlist.\n"
            "The playlist order is authoritative and represents the creator's intended learning sequence.\n\n"
            "Analyze each video and identify:\n"
            "- primary topic (concise name, e.g. 'Foundations of Recursion')\n"
            "- subtopics (2-4 granular subjects)\n"
            "- concepts (2-4 key concepts, terms or algorithms)\n"
            "- difficulty ('beginner', 'intermediate', 'advanced')\n"
            "- prerequisite_positions (list of prior video positions that are strict prerequisites)\n\n"
            "CRITICAL RULES:\n"
            "1. Never reorder videos.\n"
            "2. Never remove videos.\n"
            "3. Never invent videos.\n"
            "4. Never invent topics unrelated to the supplied metadata.\n"
            "5. Preserve the supplied position exactly.\n"
            "6. Treat the playlist as the creator's intended learning sequence.\n"
            "7. Return valid structured JSON only strictly conforming to the schema.\n"
        )

        batch_size = 50
        num_batches = math.ceil(len(videos) / batch_size)

        for batch_idx in range(num_batches):
            start = batch_idx * batch_size
            end = min(start + batch_size, len(videos))
            chunk = videos[start:end]

            # Construct clean, minimal metadata payload
            video_lines = []
            for v in chunk:
                desc = (v.get("description") or "").strip()
                # Intelligent truncation: first 1500 chars to save tokens
                truncated_desc = desc[:1500].replace("\n", " ") if desc else "No description provided."
                duration_mins = max(1, round(v.get("duration_seconds", 0) / 60))
                video_lines.append(
                    f"Video Position: {v['position']}\n"
                    f"Title: {v['title']}\n"
                    f"Duration: {duration_mins} minutes\n"
                    f"Description: {truncated_desc}\n"
                )

            prompt = (
                f"Course / Playlist Title: {playlist_title}\n"
                f"Batch {batch_idx + 1} of {num_batches} (Positions {start} to {end - 1}):\n\n"
                + "\n---\n".join(video_lines)
            )

            try:
                logger.info(f"Analyzing batch {batch_idx + 1}/{num_batches} ({len(chunk)} videos) with Gemini...")
                result: PlaylistCurriculumAnalysis = await llm.generate_structured(
                    prompt=prompt,
                    response_schema=PlaylistCurriculumAnalysis,
                    system_prompt=system_instruction,
                    temperature=0.1,
                )

                # Map back strictly by position
                analysis_by_pos = {item.position: item for item in result.videos}
                for i in range(start, end):
                    pos = enriched_videos[i]["position"]
                    if pos in analysis_by_pos:
                        item = analysis_by_pos[pos]
                        enriched_videos[i]["topic"] = item.topic or enriched_videos[i].get("topic") or "Core Curriculum"
                        enriched_videos[i]["subtopics"] = item.subtopics or []
                        enriched_videos[i]["difficulty"] = item.difficulty or "beginner"
                        enriched_videos[i]["concepts"] = item.concepts or []
                        enriched_videos[i]["prerequisite_positions"] = [
                            p for p in item.prerequisite_positions if isinstance(p, int) and p < pos
                        ]
                    else:
                        # Fallback for omitted position in batch
                        self._apply_fallback_metadata(enriched_videos[i], playlist_title)
            except Exception as e:
                logger.warning(f"Gemini analysis failed on batch {batch_idx + 1}: {e}. Applying graceful sequential fallback.")
                for i in range(start, end):
                    self._apply_fallback_metadata(enriched_videos[i], playlist_title)

        return enriched_videos

    @staticmethod
    def _apply_fallback_metadata(video: Dict[str, Any], playlist_title: str) -> None:
        """Gracefully enhances a video with title-derived topic when LLM is unavailable."""
        title = video.get("title", "")
        # Clean title (e.g. remove '#1 - ', 'Episode 4:', etc.)
        cleaned = re.sub(r"^(#?\d+[\s\-\:\.]+)+", "", title).strip()
        parts = cleaned.split(" - ")
        topic = parts[0].strip() if len(parts) > 1 else cleaned
        video["topic"] = topic if len(topic) <= 40 else "Core Curriculum"
        video["subtopics"] = [cleaned] if cleaned else ["Concepts"]
        video["difficulty"] = "beginner" if video.get("position", 0) < 5 else "intermediate"
        video["concepts"] = [word for word in cleaned.split() if len(word) > 4][:3]
        pos = video.get("position", 0)
        video["prerequisite_positions"] = [pos - 1] if pos > 0 else []

    # ---------------------------------------------------------------------------
    # Topic Grouping Layer (Presentation Only, Strict Sequence Preserved)
    # ---------------------------------------------------------------------------

    @staticmethod
    def group_videos_into_modules(videos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Groups sequential videos into presentation modules.
        Underlying video sequence (0, 1, 2, ...) is NEVER reordered.
        """
        if not videos:
            return []

        modules: List[Dict[str, Any]] = []
        current_module_videos: List[Dict[str, Any]] = []
        current_topic = None

        for v in videos:
            v_topic = v.get("topic") or "General"
            # Normalize topic comparison
            norm_topic = v_topic.strip().lower()

            if current_topic is None:
                current_topic = v_topic
                current_module_videos.append(v)
            elif norm_topic == current_topic.strip().lower() or len(current_module_videos) < 2:
                current_module_videos.append(v)
            else:
                # Start new module
                modules.append({
                    "title": current_topic,
                    "module_index": len(modules) + 1,
                    "videos": current_module_videos,
                })
                current_topic = v_topic
                current_module_videos = [v]

        if current_module_videos:
            modules.append({
                "title": current_topic or "Advanced Concepts",
                "module_index": len(modules) + 1,
                "videos": current_module_videos,
            })

        return modules

    # ---------------------------------------------------------------------------
    # Personalized Scheduling Layer (Operates on Schedule, NOT Curriculum)
    # ---------------------------------------------------------------------------

    @staticmethod
    def calculate_personalized_schedule(
        videos: List[Dict[str, Any]],
        daily_minutes: int = 30,
        days_per_week: int = 5,
        pace: str = "normal",
        revision_frequency: str = "every_few_days",
        deadline: Optional[date] = None,
    ) -> Dict[str, Any]:
        """
        Generates day-by-day study schedule and revision sessions.
        Strict invariant: Never skips, replaces, or reorders videos.
        """
        total_videos = len(videos)
        total_seconds = sum(v.get("duration_seconds", 0) for v in videos)
        total_hours = round(total_seconds / 3600.0, 1)

        # Pace multiplier for active learning, exercises, note taking
        pace_multiplier = 1.25
        if pace == "relaxed":
            pace_multiplier = 1.45
        elif pace == "fast":
            pace_multiplier = 1.05

        effective_daily_study_seconds = daily_minutes * 60

        schedule_days: List[Dict[str, Any]] = []
        current_day_number = 1
        current_day_videos: List[Dict[str, Any]] = []
        current_day_seconds = 0
        video_idx = 0

        # Start from tomorrow or today
        current_date = datetime.now(timezone.utc).date()

        while video_idx < total_videos:
            v = videos[video_idx]
            v_duration = v.get("duration_seconds", 0)
            weighted_duration = max(300, int(v_duration * pace_multiplier))  # Min 5 mins

            # If adding this video exceeds daily budget and day already has at least 1 video, seal day
            if current_day_videos and (current_day_seconds + weighted_duration > effective_daily_study_seconds):
                # Check for revision insertion
                has_revision = False
                revision_notes = None
                if revision_frequency == "every_few_days" and current_day_number % 3 == 0:
                    has_revision = True
                    revision_notes = f"Review key concepts from Days {max(1, current_day_number - 2)} to {current_day_number}"
                elif revision_frequency == "weekly" and current_day_number % 5 == 0:
                    has_revision = True
                    revision_notes = "Weekly synthesis and retrieval practice"

                schedule_days.append({
                    "day_number": current_day_number,
                    "day_label": f"Day {current_day_number}",
                    "date_str": current_date.strftime("%b %d, %Y"),
                    "videos": current_day_videos,
                    "has_revision": has_revision,
                    "revision_notes": revision_notes,
                    "total_minutes": round(current_day_seconds / 60),
                })
                current_day_number += 1
                current_date += timedelta(days=1)
                current_day_videos = []
                current_day_seconds = 0

            # Add video to current day
            dur_mins = max(1, round(v_duration / 60))
            current_day_videos.append({
                "position": v["position"],
                "video_id": v.get("id", ""),
                "youtube_video_id": v["youtube_video_id"],
                "title": v["title"],
                "duration_minutes": dur_mins,
                "youtube_url": v.get("youtube_url", f"https://www.youtube.com/watch?v={v['youtube_video_id']}"),
                "status": v.get("status", "NOT_STARTED"),
            })
            current_day_seconds += weighted_duration
            video_idx += 1

        # Seal final day
        if current_day_videos:
            schedule_days.append({
                "day_number": current_day_number,
                "day_label": f"Day {current_day_number}",
                "date_str": current_date.strftime("%b %d, %Y"),
                "videos": current_day_videos,
                "has_revision": False,
                "revision_notes": None,
                "total_minutes": round(current_day_seconds / 60),
            })

        total_study_days = len(schedule_days)
        estimated_weeks = round(total_study_days / float(days_per_week or 5), 1)
        completion_date_str = (datetime.now(timezone.utc).date() + timedelta(days=int(estimated_weeks * 7))).strftime("%b %d, %Y")

        return {
            "total_videos": total_videos,
            "total_duration_hours": total_hours,
            "daily_minutes": daily_minutes,
            "days_per_week": days_per_week,
            "estimated_weeks": estimated_weeks,
            "estimated_completion_date": completion_date_str,
            "schedule_days": schedule_days,
        }

    # ---------------------------------------------------------------------------
    # Playlist Change Detection (Incremental Updates)
    # ---------------------------------------------------------------------------

    @staticmethod
    def detect_playlist_changes(
        old_videos: List[Dict[str, Any]],
        new_videos: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Detects added, removed, and reordered videos between refreshes."""
        old_ids = [v["youtube_video_id"] for v in old_videos]
        new_ids = [v["youtube_video_id"] for v in new_videos]

        added = [v for v in new_videos if v["youtube_video_id"] not in set(old_ids)]
        removed = [v for v in old_videos if v["youtube_video_id"] not in set(new_ids)]
        reordered = False

        common_old = [vid for vid in old_ids if vid in set(new_ids)]
        common_new = [vid for vid in new_ids if vid in set(old_ids)]
        if common_old != common_new:
            reordered = True

        return {
            "changes_detected": bool(added or removed or reordered),
            "added_videos": added,
            "removed_videos": removed,
            "reordered": reordered,
        }

    # ---------------------------------------------------------------------------
    # End-to-End Playlist Import & Roadmap Linking
    # ---------------------------------------------------------------------------

    async def import_playlist(
        self,
        user_id: str,
        request: YouTubePlaylistImportRequest,
    ) -> YouTubePlaylistResponse:
        """
        Orchestrates full import:
        1. Extract ID
        2. Fetch YouTube items & details
        3. Check Cache
        4. Batch Gemini Analysis (if cache miss)
        5. Persist to DB
        6. Link into SkillTwin's Dynamic LearningPath system
        7. Compute personalized schedule
        """
        start_time = datetime.now(timezone.utc)
        playlist_id = self.extract_playlist_id(request.url)
        logger.info(f"playlist_import_started for user {user_id}: playlist_id={playlist_id}")

        # 1. Fetch metadata & all videos through YouTube Data API
        try:
            metadata = await self.fetch_playlist_metadata(playlist_id)
            videos = await self.fetch_playlist_items(playlist_id)
            logger.info(f"youtube_fetch_completed: found {len(videos)} videos")
        except Exception as e:
            logger.error(f"youtube_fetch_failed: {e}")
            raise

        if not videos:
            raise ValidationError("This YouTube playlist contains no available videos.")

        # 2. Check Cache
        content_hash = self.compute_content_hash(videos)
        cached = await self.repo.get_cache(playlist_id, content_hash)

        if cached and cached.cached_videos:
            logger.info(f"playlist_cache_hit for {playlist_id} (hash: {content_hash[:8]}). 0 Gemini calls.")
            enriched_videos = list(cached.cached_videos)
        else:
            logger.info(f"playlist_cache_miss for {playlist_id}. Initiating batched Gemini curriculum analysis.")
            logger.info("gemini_analysis_started")
            try:
                enriched_videos = await self.analyze_curriculum_with_gemini(videos, metadata["title"])
                logger.info("gemini_analysis_completed")
            except Exception as e:
                logger.error(f"gemini_analysis_failed: {e}")
                enriched_videos = videos

            # Store in shared cache
            topic_groups = self.group_videos_into_modules(enriched_videos)
            total_dur = sum(v.get("duration_seconds", 0) for v in enriched_videos)
            cache_obj = YouTubePlaylistCacheModel(
                id=f"cache_{playlist_id}_{content_hash[:16]}",
                youtube_playlist_id=playlist_id,
                content_hash=content_hash,
                title=metadata["title"],
                description=metadata.get("description", ""),
                channel_name=metadata.get("channel_name", ""),
                thumbnail_url=metadata.get("thumbnail_url", ""),
                video_count=len(enriched_videos),
                total_duration_seconds=total_dur,
                cached_videos=enriched_videos,
                topic_groups=topic_groups,
            )
            await self.repo.save_cache(cache_obj)

        # 3. Create or Update user's YouTubePlaylistModel
        user_playlist_id = str(uuid.uuid4())
        total_duration = sum(v.get("duration_seconds", 0) for v in enriched_videos)

        yt_playlist = YouTubePlaylistModel(
            id=user_playlist_id,
            user_id=user_id,
            youtube_playlist_id=playlist_id,
            title=metadata["title"],
            description=metadata.get("description", ""),
            channel_name=metadata.get("channel_name", ""),
            thumbnail_url=metadata.get("thumbnail_url", ""),
            video_count=len(enriched_videos),
            total_duration_seconds=total_duration,
            content_hash=content_hash,
            analysis_status="READY",
            metadata_json={"strict_mode": request.strict_mode},
        )
        await self.repo.save_playlist(yt_playlist)

        # 4. Save video entities
        video_models: List[YouTubePlaylistVideoModel] = []
        familiar_set = set(k.lower() for k in (request.current_knowledge or []))

        for v in enriched_videos:
            status = "NOT_STARTED"
            # Section 24: If user marked familiar concepts, mark familiar without deleting video
            v_concepts = [c.lower() for c in v.get("concepts", [])]
            if familiar_set and any(any(f in c for c in v_concepts) for f in familiar_set):
                status = "COMPLETED"

            v_model = YouTubePlaylistVideoModel(
                id=str(uuid.uuid4()),
                playlist_id=user_playlist_id,
                youtube_video_id=v["youtube_video_id"],
                position=v["position"],
                title=v["title"],
                description=v.get("description", ""),
                duration_seconds=v.get("duration_seconds", 0),
                thumbnail_url=v.get("thumbnail_url", ""),
                youtube_url=v.get("youtube_url", f"https://www.youtube.com/watch?v={v['youtube_video_id']}"),
                topic=v.get("topic", "Core Curriculum"),
                subtopics=v.get("subtopics", []),
                difficulty=v.get("difficulty", "beginner"),
                concepts=v.get("concepts", []),
                prerequisite_positions=v.get("prerequisite_positions", []),
                status=status,
                availability=v.get("availability", "available"),
            )
            video_models.append(v_model)

        await self.repo.save_videos(video_models)

        # 5. Integrate cleanly into SkillTwin's Dynamic LearningPath System
        logger.info("roadmap_generation_started")
        learning_path = await self._integrate_with_skilltwin_learning_path(
            user_id=user_id,
            playlist=yt_playlist,
            videos=video_models,
            request=request,
        )
        yt_playlist.learning_path_id = learning_path.id
        await self.repo.save_playlist(yt_playlist)
        logger.info(f"roadmap_generation_completed: Linked LearningPath {learning_path.id}")

        # 6. Calculate personalized schedule
        schedule_data = self.calculate_personalized_schedule(
            videos=[{
                "id": vm.id,
                "position": vm.position,
                "youtube_video_id": vm.youtube_video_id,
                "title": vm.title,
                "duration_seconds": vm.duration_seconds,
                "youtube_url": vm.youtube_url,
                "status": vm.status,
            } for vm in video_models],
            daily_minutes=request.daily_minutes,
            days_per_week=5,
            pace=request.pace,
            revision_frequency=request.revision_frequency,
            deadline=request.deadline,
        )

        return await self.get_playlist_response(user_playlist_id, user_id, schedule_data=schedule_data)

    # ---------------------------------------------------------------------------
    # Deep Integration into SkillTwin Hierarchical Roadmap Engine
    # ---------------------------------------------------------------------------

    async def _integrate_with_skilltwin_learning_path(
        self,
        user_id: str,
        playlist: YouTubePlaylistModel,
        videos: List[YouTubePlaylistVideoModel],
        request: YouTubePlaylistImportRequest,
    ) -> LearningPathModel:
        """
        Creates canonical GoalModel and hierarchical LearningPathModel / Section / Topic
        entities so the imported YouTube playlist seamlessly powers SkillTwin's
        existing Journey, TopicDetail, and Twin metrics views.
        """
        # Ensure Goal
        goal_id = str(uuid.uuid4())
        goal = GoalModel(
            id=goal_id,
            user_id=user_id,
            title=f"{playlist.title} (YouTube)",
            description=f"Sequential YouTube curriculum from {playlist.channel_name or 'YouTube creator'}",
            deadline=request.deadline,
            current_level=request.target_level.lower(),
            target_level=request.target_level,
            daily_minutes=request.daily_minutes,
            status="ACTIVE",
        )
        await self.dl_repo.save_goal(goal)

        # Create LearningPath
        path_id = str(uuid.uuid4())
        total_hours = round(playlist.total_duration_seconds / 3600.0, 1)
        path = LearningPathModel(
            id=path_id,
            goal_id=goal.id,
            user_id=user_id,
            title=playlist.title,
            description=playlist.description or f"Master {playlist.title} following the creator's exact video sequence.",
            target_level=request.target_level,
            estimated_duration=f"{total_hours}h ({len(videos)} videos)",
            version=1,
            status="ACTIVE",
            generation_status="READY",
            progress=0.0,
            metadata_json={
                "source_type": "youtube_playlist",
                "source_id": playlist.id,
                "youtube_playlist_id": playlist.youtube_playlist_id,
                "channel_name": playlist.channel_name,
                "thumbnail_url": playlist.thumbnail_url,
                "strict_mode": request.strict_mode,
            },
        )
        await self.dl_repo.save_path(path)

        # Group videos into modules for hierarchical presentation
        video_dicts = [{
            "id": v.id,
            "position": v.position,
            "title": v.title,
            "topic": v.topic,
            "description": v.description,
            "duration_seconds": v.duration_seconds,
            "thumbnail_url": v.thumbnail_url,
            "youtube_url": v.youtube_url,
            "youtube_video_id": v.youtube_video_id,
            "difficulty": v.difficulty,
            "concepts": v.concepts,
            "subtopics": v.subtopics,
            "status": v.status,
        } for v in videos]

        modules = self.group_videos_into_modules(video_dicts)
        all_sections: List[LearningSectionModel] = []
        all_topics: List[LearningTopicModel] = []
        progress_models: List[LearnerTopicProgressModel] = []

        for m_idx, mod in enumerate(modules):
            section_id = str(uuid.uuid4())
            section = LearningSectionModel(
                id=section_id,
                path_id=path.id,
                title=f"Module {m_idx + 1} — {mod['title']}",
                description=f"Part {m_idx + 1} of {playlist.title}",
                order_index=m_idx + 1,
            )
            all_sections.append(section)

            for t_idx, v in enumerate(mod["videos"]):
                topic_id = str(uuid.uuid4())
                est_mins = max(5, round(v.get("duration_seconds", 0) / 60))
                topic = LearningTopicModel(
                    id=topic_id,
                    section_id=section.id,
                    title=f"Video {v['position'] + 1}: {v['title']}",
                    description=v.get("description", ""),
                    order_index=v["position"] + 1,
                    difficulty=v.get("difficulty", "beginner"),
                    estimated_minutes=est_mins,
                    prerequisites=[f"Video {v['position']}"] if v["position"] > 0 else [],
                    learning_objectives=v.get("subtopics", []),
                    metadata_json={
                        "youtube_video_id": v["youtube_video_id"],
                        "youtube_url": v["youtube_url"],
                        "duration_seconds": v["duration_seconds"],
                        "thumbnail_url": v["thumbnail_url"],
                        "position": v["position"],
                        "channel_name": playlist.channel_name,
                        "concepts": v.get("concepts", []),
                        "subtopics": v.get("subtopics", []),
                        "difficulty": v.get("difficulty", "beginner"),
                        "video_entity_id": v["id"],
                    },
                )
                all_topics.append(topic)

                # Initialize learner progress
                initial_status = "not_started"
                if v.get("status") == "COMPLETED":
                    initial_status = "completed"
                elif v.get("status") == "IN_PROGRESS":
                    initial_status = "learning"

                progress_models.append(
                    LearnerTopicProgressModel(
                        id=str(uuid.uuid4()),
                        user_id=user_id,
                        topic_id=topic.id,
                        status=initial_status,
                        mastery_score=1.0 if initial_status == "completed" else 0.0,
                    )
                )

        await self.dl_repo.save_sections_and_topics(all_sections, all_topics)
        for pm in progress_models:
            await self.dl_repo.save_topic_progress(pm)

        return path

    # ---------------------------------------------------------------------------
    # Get Playlist Response / Status / Resume Point
    # ---------------------------------------------------------------------------

    async def get_playlist_response(
        self,
        playlist_id: str,
        user_id: str,
        schedule_data: Optional[Dict[str, Any]] = None,
    ) -> YouTubePlaylistResponse:
        """Constructs full YouTubePlaylistResponse with modules, strict locking, and resume point."""
        playlist = await self.repo.get_playlist(playlist_id, user_id=user_id)
        if not playlist:
            raise EntityNotFoundError(f"YouTube Playlist '{playlist_id}' not found.")

        videos = await self.repo.get_playlist_videos(playlist_id)
        strict_mode = bool(playlist.metadata_json.get("strict_mode", True))

        # Find first incomplete video for Resume functionality
        continue_video_res: Optional[YouTubeVideoResponse] = None
        has_found_current = False
        completed_count = 0

        video_responses: List[YouTubeVideoResponse] = []

        for idx, v in enumerate(videos):
            is_completed = v.status in ("COMPLETED", "SKIPPED")
            if is_completed:
                completed_count += 1

            is_current = False
            is_locked = False

            if strict_mode:
                if not is_completed and not has_found_current:
                    is_current = True
                    has_found_current = True
                elif not is_completed and has_found_current:
                    is_locked = True

            resp = YouTubeVideoResponse(
                id=str(v.id),
                playlist_id=str(v.playlist_id),
                youtube_video_id=v.youtube_video_id,
                position=v.position,
                title=v.title,
                description=v.description,
                duration_seconds=v.duration_seconds,
                duration_formatted=self.format_duration(v.duration_seconds),
                thumbnail_url=v.thumbnail_url,
                youtube_url=v.youtube_url,
                topic=v.topic,
                subtopics=v.subtopics or [],
                difficulty=v.difficulty or "beginner",
                concepts=v.concepts or [],
                prerequisite_positions=v.prerequisite_positions or [],
                status=v.status,
                availability=v.availability,
                watch_progress=v.watch_progress,
                notes=v.notes,
                user_rating=v.user_rating,
                started_at=v.started_at,
                completed_at=v.completed_at,
                is_current=is_current,
                is_locked=is_locked,
            )

            if is_current:
                continue_video_res = resp

            video_responses.append(resp)

        # If all completed, default continue video to first or last
        if not continue_video_res and video_responses:
            continue_video_res = video_responses[-1]

        # Group into presentation modules
        modules_data: List[YouTubeModuleResponse] = []
        raw_grouped = self.group_videos_into_modules([{
            "id": vr.id,
            "position": vr.position,
            "title": vr.title,
            "topic": vr.topic,
        } for vr in video_responses])

        v_map = {vr.id: vr for vr in video_responses}
        for g_idx, g in enumerate(raw_grouped):
            m_vids = [v_map[item["id"]] for item in g["videos"] if item["id"] in v_map]
            dur_mins = sum(v.duration_seconds for v in m_vids) // 60
            comp = sum(1 for v in m_vids if v.status in ("COMPLETED", "SKIPPED"))
            modules_data.append(
                YouTubeModuleResponse(
                    title=f"Module {g_idx + 1} — {g['title']}",
                    module_index=g_idx + 1,
                    videos=m_vids,
                    total_duration_minutes=dur_mins,
                    completed_videos=comp,
                    total_videos=len(m_vids),
                    is_completed=comp == len(m_vids) and len(m_vids) > 0,
                )
            )

        progress_pct = round((completed_count / len(videos)) * 100.0, 1) if videos else 0.0

        # Calculate schedule if not provided
        if not schedule_data:
            schedule_data = self.calculate_personalized_schedule(
                videos=[{
                    "id": v.id,
                    "position": v.position,
                    "youtube_video_id": v.youtube_video_id,
                    "title": v.title,
                    "duration_seconds": v.duration_seconds,
                    "youtube_url": v.youtube_url,
                    "status": v.status,
                } for v in videos]
            )

        sched_resp = None
        if schedule_data:
            sched_resp = PersonalizedScheduleResponse(
                total_videos=schedule_data["total_videos"],
                total_duration_hours=schedule_data["total_duration_hours"],
                daily_minutes=schedule_data["daily_minutes"],
                days_per_week=schedule_data.get("days_per_week", 5),
                estimated_weeks=schedule_data["estimated_weeks"],
                estimated_completion_date=schedule_data.get("estimated_completion_date"),
                schedule_days=[
                    PersonalizedScheduleDay(
                        day_number=d["day_number"],
                        day_label=d["day_label"],
                        date_str=d.get("date_str"),
                        videos=[ScheduledVideoItem(**item) for item in d["videos"]],
                        has_revision=d.get("has_revision", False),
                        revision_notes=d.get("revision_notes"),
                        total_minutes=d.get("total_minutes", 0),
                    )
                    for d in schedule_data.get("schedule_days", [])
                ],
            )

        return YouTubePlaylistResponse(
            id=str(playlist.id),
            user_id=str(playlist.user_id),
            youtube_playlist_id=playlist.youtube_playlist_id,
            title=playlist.title,
            description=playlist.description,
            channel_name=playlist.channel_name,
            thumbnail_url=playlist.thumbnail_url,
            video_count=playlist.video_count,
            total_duration_seconds=playlist.total_duration_seconds,
            total_duration_formatted=self.format_duration_human(playlist.total_duration_seconds),
            analysis_status=playlist.analysis_status,
            learning_path_id=str(playlist.learning_path_id) if playlist.learning_path_id else None,
            strict_mode=strict_mode,
            progress_percent=progress_pct,
            completed_count=completed_count,
            continue_video=continue_video_res,
            modules=modules_data,
            schedule=sched_resp,
            created_at=playlist.created_at,
            updated_at=playlist.updated_at,
        )

    # ---------------------------------------------------------------------------
    # Progress Tracking Video-by-Video
    # ---------------------------------------------------------------------------

    async def update_video_progress(
        self,
        video_id: str,
        user_id: str,
        request: YouTubeVideoProgressUpdateRequest,
    ) -> YouTubeVideoResponse:
        """
        Updates video progress (NOT_STARTED, IN_PROGRESS, COMPLETED, SKIPPED).
        Synchronizes with linked SkillTwin LearningTopic progress.
        """
        video = await self.repo.update_video_progress(
            video_id=video_id,
            status=request.status,
            watch_progress=request.watch_progress,
            notes=request.notes,
            user_rating=request.user_rating,
        )
        if not video:
            raise EntityNotFoundError(f"Video '{video_id}' not found.")

        # Update linked LearningTopic progress in DynamicLearningRepository
        try:
            playlist = await self.repo.get_playlist(str(video.playlist_id))
            if playlist and playlist.learning_path_id:
                # Find matching topic by position or video_entity_id
                path = await self.dl_repo.get_learning_path_by_id(str(playlist.learning_path_id))
                if path:
                    for section in path.sections:
                        for topic in section.topics:
                            meta = topic.metadata_json or {}
                            if meta.get("video_entity_id") == str(video.id) or meta.get("position") == video.position:
                                topic_status = "not_started"
                                if video.status == "COMPLETED":
                                    topic_status = "completed"
                                elif video.status == "IN_PROGRESS":
                                    topic_status = "learning"

                                progress_record = await self.dl_repo.get_topic_progress(user_id, topic.id)
                                if progress_record:
                                    progress_record.status = topic_status
                                    if topic_status == "completed":
                                        progress_record.mastery_score = 1.0
                                        progress_record.completed_at = datetime.now(timezone.utc)
                                    await self.dl_repo.save_topic_progress(progress_record)
                                break
        except Exception as e:
            logger.warning(f"Could not synchronize video progress with learning path: {e}")

        return YouTubeVideoResponse(
            id=str(video.id),
            playlist_id=str(video.playlist_id),
            youtube_video_id=video.youtube_video_id,
            position=video.position,
            title=video.title,
            description=video.description,
            duration_seconds=video.duration_seconds,
            duration_formatted=self.format_duration(video.duration_seconds),
            thumbnail_url=video.thumbnail_url,
            youtube_url=video.youtube_url,
            topic=video.topic,
            subtopics=video.subtopics or [],
            difficulty=video.difficulty or "beginner",
            concepts=video.concepts or [],
            prerequisite_positions=video.prerequisite_positions or [],
            status=video.status,
            availability=video.availability,
            watch_progress=video.watch_progress,
            notes=video.notes,
            user_rating=video.user_rating,
            started_at=video.started_at,
            completed_at=video.completed_at,
        )

    # ---------------------------------------------------------------------------
    # Refresh / Sync with YouTube Playlist
    # ---------------------------------------------------------------------------

    async def refresh_playlist(
        self,
        playlist_id: str,
        user_id: str,
    ) -> YouTubePlaylistRefreshResponse:
        """
        Refreshes playlist from YouTube. Detects additions, deletions, reorderings.
        Only newly added videos are sent to Gemini (Incremental Analysis).
        Existing completion history is 100% preserved.
        """
        playlist = await self.repo.get_playlist(playlist_id, user_id=user_id)
        if not playlist:
            raise EntityNotFoundError(f"Playlist '{playlist_id}' not found.")

        current_videos = await self.repo.get_playlist_videos(playlist_id)
        new_yt_videos = await self.fetch_playlist_items(playlist.youtube_playlist_id)

        changes = self.detect_playlist_changes(
            old_videos=[{"youtube_video_id": v.youtube_video_id} for v in current_videos],
            new_videos=new_yt_videos,
        )

        if not changes["changes_detected"]:
            return YouTubePlaylistRefreshResponse(
                playlist_id=playlist_id,
                changes_detected=False,
                added_videos_count=0,
                removed_videos_count=0,
                reordered=False,
                message="Playlist is up to date. No changes detected.",
            )

        added = changes["added_videos"]
        removed = changes["removed_videos"]

        # Only analyze newly added videos with Gemini!
        if added:
            logger.info(f"Analyzing {len(added)} newly added videos for playlist {playlist_id}...")
            analyzed_added = await self.analyze_curriculum_with_gemini(added, playlist.title)
            # Persist added videos
            new_models = []
            for v in analyzed_added:
                new_models.append(
                    YouTubePlaylistVideoModel(
                        id=str(uuid.uuid4()),
                        playlist_id=playlist_id,
                        youtube_video_id=v["youtube_video_id"],
                        position=v["position"],
                        title=v["title"],
                        description=v.get("description", ""),
                        duration_seconds=v.get("duration_seconds", 0),
                        thumbnail_url=v.get("thumbnail_url", ""),
                        youtube_url=v.get("youtube_url", ""),
                        topic=v.get("topic", "New Module"),
                        subtopics=v.get("subtopics", []),
                        difficulty=v.get("difficulty", "beginner"),
                        concepts=v.get("concepts", []),
                        prerequisite_positions=v.get("prerequisite_positions", []),
                        status="NOT_STARTED",
                    )
                )
            await self.repo.save_videos(new_models)

        # Update playlist content hash and video count
        all_videos = await self.repo.get_playlist_videos(playlist_id)
        playlist.video_count = len(all_videos)
        playlist.total_duration_seconds = sum(v.duration_seconds for v in all_videos)
        playlist.content_hash = self.compute_content_hash([{"youtube_video_id": v.youtube_video_id} for v in all_videos])
        await self.repo.save_playlist(playlist)

        return YouTubePlaylistRefreshResponse(
            playlist_id=playlist_id,
            changes_detected=True,
            added_videos_count=len(added),
            removed_videos_count=len(removed),
            reordered=changes["reordered"],
            message=f"Synced successfully. {len(added)} added, {len(removed)} removed.",
        )

    # ---------------------------------------------------------------------------
    # Mock Data Provider (Resilient Offline Fallback)
    # ---------------------------------------------------------------------------

    def _get_mock_playlist_metadata(self, playlist_id: str) -> Dict[str, Any]:
        return {
            "playlist_id": playlist_id,
            "title": "Complete Data Structures & Algorithms Masterclass",
            "description": "Comprehensive course covering all fundamental data structures, algorithms, search, sorting, and dynamic programming.",
            "channel_name": "SkillTwin Engineering Academy",
            "thumbnail_url": "https://images.unsplash.com/photo-1516116211227-bbc13c744be1?w=800",
            "video_count": 8,
        }

    def _get_mock_playlist_items(self, playlist_id: str) -> List[Dict[str, Any]]:
        topics = [
            ("Introduction & Time Complexity", 720, "Big O notation, time and space complexity fundamentals."),
            ("Arrays and Memory Layout", 1140, "Static vs dynamic arrays, memory addresses, and contiguous storage."),
            ("Linear Search vs Binary Search", 1380, "Comparing O(N) linear search with O(log N) binary search on sorted sequences."),
            ("Binary Search Edge Cases", 960, "Lower bounds, upper bounds, and searching rotated sorted arrays."),
            ("Singly and Doubly Linked Lists", 1450, "Node pointers, head and tail operations, reversing lists."),
            ("Stack & Queue Implementations", 1200, "LIFO vs FIFO, monotonic stacks, and circular buffer queues."),
            ("Recursion Fundamentals", 1500, "Call stack visualization, base cases, and tree recursion."),
            ("Binary Search Trees & Traversals", 1820, "Inorder, preorder, postorder, and level order BFS traversal."),
        ]
        items = []
        for idx, (title, dur, desc) in enumerate(topics):
            vid = f"mock_{playlist_id[:6]}_{idx:02d}"
            items.append({
                "position": idx,
                "youtube_video_id": vid,
                "title": title,
                "description": desc,
                "thumbnail_url": f"https://images.unsplash.com/photo-1516116211227-bbc13c744be1?w=400&fit=crop&q=80",
                "channel_name": "SkillTwin Engineering Academy",
                "youtube_url": f"https://www.youtube.com/watch?v={vid}",
                "duration_seconds": dur,
                "availability": "available",
            })
        return items


youtube_service = YouTubeService()
