import pytest
from datetime import date, timedelta
from app.services.youtube_service import YouTubeService, youtube_service
from app.schemas.youtube import YouTubePlaylistImportRequest, YouTubeVideoProgressUpdateRequest
from app.core.exceptions import ValidationError


def test_youtube_url_parsing():
    service = youtube_service

    # Valid playlist URLs
    assert service.extract_playlist_id("https://www.youtube.com/playlist?list=PL4cUxeGkcC9gUxtNzTrigytTE424KAw0q") == "PL4cUxeGkcC9gUxtNzTrigytTE424KAw0q"
    assert service.extract_playlist_id("https://youtube.com/playlist?list=PL4cUxeGkcC9gUxtNzTrigytTE424KAw0q") == "PL4cUxeGkcC9gUxtNzTrigytTE424KAw0q"
    assert service.extract_playlist_id("http://m.youtube.com/playlist?list=PL4cUxeGkcC9gUxtNzTrigytTE424KAw0q") == "PL4cUxeGkcC9gUxtNzTrigytTE424KAw0q"
    assert service.extract_playlist_id("https://www.youtube.com/watch?v=0pThnRneDjw&list=PL4cUxeGkcC9gUxtNzTrigytTE424KAw0q&index=1") == "PL4cUxeGkcC9gUxtNzTrigytTE424KAw0q"
    assert service.extract_playlist_id("https://youtu.be/0pThnRneDjw?list=PL4cUxeGkcC9gUxtNzTrigytTE424KAw0q&si=abc") == "PL4cUxeGkcC9gUxtNzTrigytTE424KAw0q"
    assert service.extract_playlist_id("PL4cUxeGkcC9gUxtNzTrigytTE424KAw0q") == "PL4cUxeGkcC9gUxtNzTrigytTE424KAw0q"

    # Invalid: Video URL without playlist
    with pytest.raises(ValidationError):
        service.extract_playlist_id("https://www.youtube.com/watch?v=0pThnRneDjw")

    # Invalid: Random text / Malformed
    with pytest.raises(ValidationError):
        service.extract_playlist_id("https://vimeo.com/channels/staffpicks/123456")

    with pytest.raises(ValidationError):
        service.extract_playlist_id("not a url at all")

    with pytest.raises(ValidationError):
        service.extract_playlist_id("")


def test_iso8601_duration_parsing():
    service = youtube_service
    assert service.parse_iso8601_duration("PT1H23M45S") == 1 * 3600 + 23 * 60 + 45
    assert service.parse_iso8601_duration("PT18M") == 18 * 60
    assert service.parse_iso8601_duration("PT45S") == 45
    assert service.parse_iso8601_duration("PT1H") == 3600
    assert service.parse_iso8601_duration("P1DT2H") == 86400 + 7200
    assert service.parse_iso8601_duration("") == 0
    assert service.parse_iso8601_duration(None) == 0


def test_content_hashing_and_sequence_invariance():
    service = youtube_service
    videos_1 = [
        {"youtube_video_id": "v1"},
        {"youtube_video_id": "v2"},
        {"youtube_video_id": "v3"},
    ]
    videos_2 = [
        {"youtube_video_id": "v1"},
        {"youtube_video_id": "v2"},
        {"youtube_video_id": "v3"},
    ]
    # Reordered
    videos_reordered = [
        {"youtube_video_id": "v2"},
        {"youtube_video_id": "v1"},
        {"youtube_video_id": "v3"},
    ]

    hash_1 = service.compute_content_hash(videos_1)
    hash_2 = service.compute_content_hash(videos_2)
    hash_reordered = service.compute_content_hash(videos_reordered)

    assert hash_1 == hash_2
    assert hash_1 != hash_reordered


def test_topic_grouping_preserves_strict_sequence():
    service = youtube_service
    videos = [
        {"position": 0, "title": "Intro to Java", "topic": "Java Fundamentals"},
        {"position": 1, "title": "Variables & Data Types", "topic": "Java Fundamentals"},
        {"position": 2, "title": "Control Flow & Loops", "topic": "Java Fundamentals"},
        {"position": 3, "title": "Array Basics", "topic": "Arrays & Strings"},
        {"position": 4, "title": "Multi-dimensional Arrays", "topic": "Arrays & Strings"},
        {"position": 5, "title": "Binary Search", "topic": "Searching Algorithms"},
    ]

    modules = service.group_videos_into_modules(videos)
    assert len(modules) >= 2

    # Verify positions across all modules are strictly monotonic: 0, 1, 2, 3, 4, 5
    flattened_positions = []
    for mod in modules:
        for v in mod["videos"]:
            flattened_positions.append(v["position"])

    assert flattened_positions == [0, 1, 2, 3, 4, 5]


def test_personalization_schedule_does_not_change_video_sequence():
    service = youtube_service
    videos = [
        {"id": f"vid_{i}", "position": i, "youtube_video_id": f"y_{i}", "title": f"Video {i}", "duration_seconds": 1200, "status": "NOT_STARTED"}
        for i in range(10)
    ]

    # Schedule with 30 mins/day
    sched_30 = service.calculate_personalized_schedule(videos, daily_minutes=30, pace="normal")
    # Schedule with 60 mins/day
    sched_60 = service.calculate_personalized_schedule(videos, daily_minutes=60, pace="normal")

    # In 60 mins/day, total study days should be fewer than in 30 mins/day
    assert len(sched_60["schedule_days"]) <= len(sched_30["schedule_days"])

    # Under both schedules, video order is strictly 0..9!
    seq_30 = [v["position"] for day in sched_30["schedule_days"] for v in day["videos"]]
    seq_60 = [v["position"] for day in sched_60["schedule_days"] for v in day["videos"]]

    assert seq_30 == list(range(10))
    assert seq_60 == list(range(10))


def test_change_detection():
    service = youtube_service
    old_videos = [{"youtube_video_id": "v1"}, {"youtube_video_id": "v2"}, {"youtube_video_id": "v3"}]
    # No changes
    assert not service.detect_playlist_changes(old_videos, old_videos)["changes_detected"]

    # Added video
    new_with_added = [{"youtube_video_id": "v1"}, {"youtube_video_id": "v2"}, {"youtube_video_id": "v3"}, {"youtube_video_id": "v4"}]
    res_added = service.detect_playlist_changes(old_videos, new_with_added)
    assert res_added["changes_detected"]
    assert len(res_added["added_videos"]) == 1

    # Reordered
    reordered = [{"youtube_video_id": "v2"}, {"youtube_video_id": "v1"}, {"youtube_video_id": "v3"}]
    res_reordered = service.detect_playlist_changes(old_videos, reordered)
    assert res_reordered["changes_detected"]
    assert res_reordered["reordered"]


@pytest.mark.asyncio
async def test_end_to_end_youtube_import_and_progress(async_client, auth_headers):
    # 1. Import Playlist
    import_payload = {
        "url": "https://www.youtube.com/playlist?list=PL4cUxeGkcC9gUxtNzTrigytTE424KAw0q",
        "daily_minutes": 45,
        "target_level": "Intermediate",
        "pace": "normal",
        "strict_mode": True,
    }

    res = await async_client.post(
        "/api/v1/youtube/playlists/import",
        json=import_payload,
        headers=auth_headers,
    )
    assert res.status_code == 201
    data = res.json()
    assert data["youtube_playlist_id"] == "PL4cUxeGkcC9gUxtNzTrigytTE424KAw0q"
    assert data["video_count"] > 0
    assert data["strict_mode"] is True
    assert data["continue_video"] is not None
    assert data["continue_video"]["position"] == 0
    assert data["continue_video"]["is_current"] is True

    playlist_id = data["id"]
    learning_path_id = data["learning_path_id"]
    assert learning_path_id is not None

    # 2. Duplicate import (Test cache hit)
    res_duplicate = await async_client.post(
        "/api/v1/youtube/playlists/import",
        json=import_payload,
        headers=auth_headers,
    )
    assert res_duplicate.status_code == 201

    # 3. Get Playlist detail
    res_get = await async_client.get(
        f"/api/v1/youtube/playlists/{playlist_id}",
        headers=auth_headers,
    )
    assert res_get.status_code == 200
    detail = res_get.json()
    assert len(detail["modules"]) > 0

    all_videos = [v for mod in detail["modules"] for v in mod["videos"]]
    assert len(all_videos) >= 2
    first_video = all_videos[0]
    second_video = all_videos[1]
    assert first_video["is_current"] is True
    # In strict mode, second video is locked until first is completed!
    assert second_video["is_locked"] is True

    # 4. Update Progress: Complete First Video
    res_patch = await async_client.patch(
        f"/api/v1/youtube/videos/{first_video['id']}/progress",
        json={"status": "COMPLETED", "watch_progress": 1.0, "user_rating": 5.0},
        headers=auth_headers,
    )
    assert res_patch.status_code == 200
    patched_video = res_patch.json()
    assert patched_video["status"] == "COMPLETED"

    # 5. Verify Resume Point Advanced to Second Video
    res_after = await async_client.get(
        f"/api/v1/youtube/playlists/{playlist_id}",
        headers=auth_headers,
    )
    detail_after = res_after.json()
    assert detail_after["continue_video"]["position"] == 1
    assert detail_after["continue_video"]["is_current"] is True

    # 6. Recalculate schedule with 90 mins/day
    res_sched = await async_client.post(
        f"/api/v1/youtube/playlists/{playlist_id}/schedule",
        json={"daily_minutes": 90, "pace": "fast", "revision_frequency": "weekly"},
        headers=auth_headers,
    )
    assert res_sched.status_code == 200
    sched_data = res_sched.json()
    assert sched_data["daily_minutes"] == 90
    assert len(sched_data["schedule_days"]) > 0

    # 7. Check that linked LearningPath is accessible in SkillTwin's Dynamic Learning system
    res_lp = await async_client.get(
        f"/api/v1/learning-paths/{learning_path_id}",
        headers=auth_headers,
    )
    assert res_lp.status_code == 200
    lp_data = res_lp.json()
    assert lp_data["id"] == learning_path_id
    assert len(lp_data["sections"]) > 0
