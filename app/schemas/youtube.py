from datetime import datetime, date
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Client Requests
# ---------------------------------------------------------------------------

class YouTubePlaylistImportRequest(BaseModel):
    url: str = Field(..., description="YouTube playlist URL or ID")
    daily_minutes: int = Field(default=30, ge=5, le=480, description="Available daily study time in minutes")
    target_level: str = Field(default="Intermediate", description="Desired depth (Beginner, Intermediate, Expert, Interview Ready)")
    deadline: Optional[date] = Field(default=None, description="Optional target completion deadline")
    current_knowledge: Optional[List[str]] = Field(default=None, description="Known concepts or topics to mark familiar")
    pace: str = Field(default="normal", description="Study pacing: relaxed, normal, fast")
    revision_frequency: str = Field(default="every_few_days", description="Revision placement: none, weekly, every_few_days")
    strict_mode: bool = Field(default=True, description="Enforce sequential video progression")


class YouTubeVideoProgressUpdateRequest(BaseModel):
    status: str = Field(..., description="NOT_STARTED, IN_PROGRESS, COMPLETED, SKIPPED")
    watch_progress: float = Field(default=0.0, ge=0.0, le=1.0, description="Progress through video 0.0 - 1.0")
    notes: Optional[str] = Field(default=None, description="Personal notes for video")
    user_rating: Optional[float] = Field(default=None, ge=1.0, le=5.0, description="1-5 rating")


class YouTubeScheduleRecalculateRequest(BaseModel):
    daily_minutes: int = Field(default=30, ge=5, le=480)
    pace: str = Field(default="normal")
    revision_frequency: str = Field(default="every_few_days")
    deadline: Optional[date] = None


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------

class YouTubeVideoResponse(BaseModel):
    id: str
    playlist_id: str
    youtube_video_id: str
    position: int
    title: str
    description: Optional[str] = None
    duration_seconds: int = 0
    duration_formatted: str = "00:00"
    thumbnail_url: Optional[str] = None
    youtube_url: str
    topic: Optional[str] = None
    subtopics: List[str] = Field(default_factory=list)
    difficulty: str = "beginner"
    concepts: List[str] = Field(default_factory=list)
    prerequisite_positions: List[int] = Field(default_factory=list)
    status: str = "NOT_STARTED"
    availability: str = "available"
    watch_progress: float = 0.0
    notes: Optional[str] = None
    user_rating: Optional[float] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    is_current: bool = False
    is_locked: bool = False


class YouTubeModuleResponse(BaseModel):
    title: str
    module_index: int
    videos: List[YouTubeVideoResponse] = Field(default_factory=list)
    total_duration_minutes: int = 0
    completed_videos: int = 0
    total_videos: int = 0
    is_completed: bool = False


class ScheduledVideoItem(BaseModel):
    position: int
    video_id: str
    youtube_video_id: str
    title: str
    duration_minutes: int
    youtube_url: str
    status: str = "NOT_STARTED"


class PersonalizedScheduleDay(BaseModel):
    day_number: int
    day_label: str
    date_str: Optional[str] = None
    videos: List[ScheduledVideoItem] = Field(default_factory=list)
    has_revision: bool = False
    revision_notes: Optional[str] = None
    total_minutes: int = 0


class PersonalizedScheduleResponse(BaseModel):
    total_videos: int
    total_duration_hours: float
    daily_minutes: int
    days_per_week: int = 5
    estimated_weeks: float
    estimated_completion_date: Optional[str] = None
    schedule_days: List[PersonalizedScheduleDay] = Field(default_factory=list)


class YouTubePlaylistResponse(BaseModel):
    id: str
    user_id: str
    youtube_playlist_id: str
    title: str
    description: Optional[str] = None
    channel_name: Optional[str] = None
    thumbnail_url: Optional[str] = None
    video_count: int
    total_duration_seconds: int
    total_duration_formatted: str = "0h 0m"
    analysis_status: str
    learning_path_id: Optional[str] = None
    strict_mode: bool = True
    progress_percent: float = 0.0
    completed_count: int = 0
    continue_video: Optional[YouTubeVideoResponse] = None
    modules: List[YouTubeModuleResponse] = Field(default_factory=list)
    schedule: Optional[PersonalizedScheduleResponse] = None
    created_at: datetime
    updated_at: datetime


class YouTubePlaylistRefreshResponse(BaseModel):
    playlist_id: str
    changes_detected: bool
    added_videos_count: int = 0
    removed_videos_count: int = 0
    reordered: bool = False
    message: str
