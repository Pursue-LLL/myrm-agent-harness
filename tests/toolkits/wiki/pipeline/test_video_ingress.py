"""Tests for video raw ingress and transcript processing in Wiki pipeline."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from langchain_core.documents import Document
import pytest

from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.ingress.types import (
    MediaIngressRequest,
    MediaKeyframe,
    MediaTranscriptSegment,
    VideoUrlIngressRequest,
)
from myrm_agent_harness.toolkits.wiki.pipeline.ingress.video_ingress import (
    adaptive_merge_segments,
    format_timestamp,
    parse_timestamp_str,
    parse_transcript_text_to_segments,
    publish_media_ingress,
    publish_video_url_ingress,
)
from myrm_agent_harness.toolkits.wiki.pipeline.raw_gate import RawConflictPolicy


@pytest.fixture
def temp_structure(tmp_path) -> WikiStructure:
    structure = WikiStructure(base_dir=tmp_path)
    structure.ensure_structure()
    return structure


def test_format_and_parse_timestamp() -> None:
    assert format_timestamp(0) == "00:00"
    assert format_timestamp(65) == "01:05"
    assert format_timestamp(3665) == "01:01:05"

    assert parse_timestamp_str("00:00") == 0.0
    assert parse_timestamp_str("01:05") == 65.0
    assert parse_timestamp_str("01:01:05") == 3665.0


def test_adaptive_merge_segments() -> None:
    segments = [
        MediaTranscriptSegment(start_seconds=0.0, end_seconds=3.0, text="Hello"),
        MediaTranscriptSegment(start_seconds=3.0, end_seconds=6.0, text="world"),
        MediaTranscriptSegment(start_seconds=6.0, end_seconds=10.0, text="this is a test"),
    ]
    merged = adaptive_merge_segments(segments, window_duration_seconds=30, window_max_chars=100)
    assert len(merged) == 1
    assert merged[0].start_seconds == 0.0
    assert merged[0].end_seconds == 10.0
    assert merged[0].text == "Hello world this is a test"


def test_adaptive_merge_segments_speaker_boundary() -> None:
    segments = [
        MediaTranscriptSegment(start_seconds=0.0, end_seconds=3.0, text="Hi Alice", speaker="Bob"),
        MediaTranscriptSegment(start_seconds=3.0, end_seconds=6.0, text="Hi Bob", speaker="Alice"),
    ]
    merged = adaptive_merge_segments(segments, window_duration_seconds=30, window_max_chars=100)
    assert len(merged) == 2
    assert merged[0].speaker == "Bob"
    assert merged[1].speaker == "Alice"


def test_parse_transcript_text_to_segments() -> None:
    raw_text = "00:05 First line\n00:15 Second line\n01:30 Third line"
    segments = parse_transcript_text_to_segments(raw_text)
    assert len(segments) == 3
    assert segments[0].start_seconds == 5.0
    assert segments[0].text == "First line"
    assert segments[1].start_seconds == 15.0
    assert segments[2].start_seconds == 90.0


@pytest.mark.asyncio
async def test_publish_video_url_ingress_bilibili(temp_structure: WikiStructure) -> None:
    fake_doc = Document(
        page_content="00:00 Welcome to Bilibili course\n00:30 System architecture explanation",
        metadata={
            "title": "Clean Architecture Lecture",
            "author_name": "TechGuru",
            "duration": "10:00",
            "bvid": "BV1xx411c7Xz",
        },
    )

    with patch(
        "myrm_agent_harness.toolkits.wiki.pipeline.ingress.video_ingress.extract_bilibili_subtitle",
        new=AsyncMock(return_value=fake_doc),
    ):
        result = await publish_video_url_ingress(
            temp_structure,
            VideoUrlIngressRequest(
                url="https://www.bilibili.com/video/BV1xx411c7Xz",
                folder_path="videos",
            ),
        )

    assert result.written is True
    assert result.conflict is False
    assert result.relative_path.startswith("videos/")
    raw_path = temp_structure.get_raw_file_path(result.relative_path)
    assert raw_path.is_file()
    content = raw_path.read_text(encoding="utf-8")
    assert "Clean Architecture Lecture" in content
    assert "TechGuru" in content
    assert "content_type: \"video\"" in content
    assert "### [00:00 - 00:30]" in content or "### [00:00 -" in content


@pytest.mark.asyncio
async def test_publish_video_url_ingress_youtube(temp_structure: WikiStructure) -> None:
    fake_doc = Document(
        page_content="00:02 Hello everyone\n00:45 Today we learn quantum computing",
        metadata={
            "title": "Quantum Physics 101",
            "author_name": "MIT OpenCourseWare",
            "duration": "45:00",
        },
    )

    with patch(
        "myrm_agent_harness.toolkits.wiki.pipeline.ingress.video_ingress.extract_youtube_transcript",
        new=AsyncMock(return_value=fake_doc),
    ):
        result = await publish_video_url_ingress(
            temp_structure,
            VideoUrlIngressRequest(
                url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                folder_path="lectures",
            ),
        )

    assert result.written is True
    assert result.relative_path.startswith("lectures/")
    raw_path = temp_structure.get_raw_file_path(result.relative_path)
    assert raw_path.is_file()
    content = raw_path.read_text(encoding="utf-8")
    assert "Quantum Physics 101" in content
    assert "MIT OpenCourseWare" in content


@pytest.mark.asyncio
async def test_publish_media_ingress_with_keyframes(temp_structure: WikiStructure) -> None:
    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    request = MediaIngressRequest(
        title="Local Presentation",
        media_filename="presentation.mp4",
        duration_seconds=120.0,
        segments=(
            MediaTranscriptSegment(start_seconds=0.0, end_seconds=15.0, text="Intro slide"),
            MediaTranscriptSegment(start_seconds=15.0, end_seconds=60.0, text="Architecture diagram"),
        ),
        keyframes=(
            MediaKeyframe(
                timestamp_seconds=20.0,
                image_bytes=fake_png,
                mime_type="image/png",
            ),
        ),
    )

    result = await publish_media_ingress(temp_structure, request)
    assert result.written is True
    assert result.asset_stats.stored == 1
    raw_path = temp_structure.get_raw_file_path(result.relative_path)
    content = raw_path.read_text(encoding="utf-8")
    assert "Local Presentation" in content
    assert "wiki/assets/" in content
