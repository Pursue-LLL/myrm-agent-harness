"""Wiki video raw ingress (YouTube, Bilibili & local media transcripts) → publish_raw.

[INPUT]
- pipeline.raw_gate (POS: raw publication gate)
- toolkits.web_fetch.extractors (POS: YouTube & Bilibili transcript extractors)
- ingress.asset_store (POS: keyframes & media asset storage)

[OUTPUT]
- publish_video_url_ingress: Online video URL transcript extraction & ingress
- publish_media_ingress: Direct media transcript & keyframe ingestion
- adaptive_merge_segments: Sliding window segment aggregation

[POS]
Video & audio media raw ingress pipeline. Transforms timestamped video transcripts
into structured Markdown with second-level timestamps and publishes to Raw Gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import logging
from pathlib import Path
import re
from typing import Sequence

from myrm_agent_harness.toolkits.web_fetch.extractors.bilibili_extractor import (
    extract_bilibili_subtitle,
    is_bilibili_url,
)
from myrm_agent_harness.toolkits.web_fetch.extractors.youtube_extractor import (
    extract_youtube_transcript,
)
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.ingress.asset_store import (
    store_asset_bytes,
    store_media_asset_bytes,
)
from myrm_agent_harness.toolkits.wiki.pipeline.ingress.types import (
    ClipIngressResult,
    IngressAssetStats,
    MediaIngressRequest,
    MediaKeyframe,
    MediaTranscriptSegment,
    VideoUrlIngressRequest,
)
from myrm_agent_harness.toolkits.wiki.pipeline.raw_gate import (
    RawConflictPolicy,
    RawGateError,
    RawPublishRequest,
    publish_raw,
)

logger = logging.getLogger(__name__)

_TITLE_CLEAN_RE = re.compile(r"[^\w\s-]", re.UNICODE)
_TIMESTAMP_LINE_RE = re.compile(
    r"^(?:\[?(\d{1,2}:\d{2}(?::\d{2})?)\]?)\s*(.*)$"
)


@dataclass(frozen=True, slots=True)
class MergedVideoSegment:
    """Aggregated video transcript segment across a semantic time window."""

    start_seconds: float
    end_seconds: float
    text: str
    speaker: str | None = None


def format_timestamp(seconds: float) -> str:
    """Format total seconds into MM:SS or HH:MM:SS."""
    sec_int = max(0, int(round(seconds)))
    hours = sec_int // 3600
    minutes = (sec_int % 3600) // 60
    rem_secs = sec_int % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{rem_secs:02d}"
    return f"{minutes:02d}:{rem_secs:02d}"


def parse_timestamp_str(time_str: str) -> float:
    """Parse MM:SS or HH:MM:SS string to float seconds."""
    parts = [int(p) for p in time_str.strip().split(":") if p.isdigit()]
    if len(parts) == 3:
        return float(parts[0] * 3600 + parts[1] * 60 + parts[2])
    if len(parts) == 2:
        return float(parts[0] * 60 + parts[1])
    if len(parts) == 1:
        return float(parts[0])
    return 0.0


def adaptive_merge_segments(
    segments: Sequence[MediaTranscriptSegment],
    *,
    window_duration_seconds: int = 45,
    window_max_chars: int = 350,
) -> list[MergedVideoSegment]:
    """Aggregate fine-grained subtitle lines into coherent semantic paragraphs.

    Prevents fragmenting text into 1-2 second slivers while preserving
    second-level temporal bounding for jumping to video points.
    """
    if not segments:
        return []

    merged: list[MergedVideoSegment] = []
    current_start = segments[0].start_seconds
    current_end = segments[0].end_seconds
    current_texts: list[str] = []
    current_len = 0
    current_speaker = segments[0].speaker

    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue

        speaker_changed = seg.speaker != current_speaker and seg.speaker is not None
        duration_exceeded = (seg.end_seconds - current_start) >= window_duration_seconds
        chars_exceeded = (current_len + len(text)) >= window_max_chars

        if current_texts and (speaker_changed or duration_exceeded or chars_exceeded):
            merged.append(
                MergedVideoSegment(
                    start_seconds=current_start,
                    end_seconds=current_end,
                    text=" ".join(current_texts),
                    speaker=current_speaker,
                )
            )
            current_start = seg.start_seconds
            current_end = seg.end_seconds
            current_texts = [text]
            current_len = len(text)
            current_speaker = seg.speaker
        else:
            current_texts.append(text)
            current_len += len(text)
            current_end = max(current_end, seg.end_seconds)
            if current_speaker is None and seg.speaker:
                current_speaker = seg.speaker

    if current_texts:
        merged.append(
            MergedVideoSegment(
                start_seconds=current_start,
                end_seconds=current_end,
                text=" ".join(current_texts),
                speaker=current_speaker,
            )
        )

    return merged


def parse_transcript_text_to_segments(text: str) -> list[MediaTranscriptSegment]:
    """Convert line-based timestamp text (MM:SS Text) to structured segments."""
    lines = text.strip().splitlines()
    raw_parsed: list[tuple[float, str]] = []

    for line in lines:
        cleaned = line.strip()
        if not cleaned:
            continue
        match = _TIMESTAMP_LINE_RE.match(cleaned)
        if match:
            t_str, content = match.group(1), match.group(2).strip()
            sec = parse_timestamp_str(t_str)
            raw_parsed.append((sec, content))
        else:
            if raw_parsed:
                prev_sec, prev_text = raw_parsed[-1]
                raw_parsed[-1] = (prev_sec, f"{prev_text} {cleaned}")
            else:
                raw_parsed.append((0.0, cleaned))

    segments: list[MediaTranscriptSegment] = []
    for i, (start_sec, content) in enumerate(raw_parsed):
        if i + 1 < len(raw_parsed):
            end_sec = max(start_sec + 2.0, raw_parsed[i + 1][0])
        else:
            end_sec = start_sec + 5.0
        segments.append(
            MediaTranscriptSegment(
                start_seconds=start_sec,
                end_seconds=end_sec,
                text=content,
            )
        )

    return segments


def _slugify(text: str, fallback_hash: str) -> str:
    cleaned = _TITLE_CLEAN_RE.sub("", text.lower())
    cleaned = re.sub(r"[\s_]+", "-", cleaned).strip("-")
    if not cleaned:
        cleaned = f"video_{fallback_hash[:8]}"
    return cleaned[:60]


def build_video_markdown(
    *,
    title: str,
    source_url: str,
    duration_str: str,
    platform: str,
    author: str,
    merged_segments: Sequence[MergedVideoSegment],
    keyframes_map: dict[float, str] | None = None,
) -> str:
    """Generate standardized Markdown with Frontmatter and timestamp sections."""
    lines: list[str] = [
        "---",
        f'title: "{title.replace(chr(34), "")}"',
        f'source_url: "{source_url.replace(chr(34), "")}"',
        'content_type: "video"',
        f'platform: "{platform}"',
        f'duration: "{duration_str}"',
        f'author: "{author.replace(chr(34), "")}"',
        f"clipped_at: {datetime.now(UTC).isoformat()}",
        "---",
        "",
        f"# {title}",
        "",
        f"> **来源平台:** {platform.title()} | **时长:** {duration_str or '未知'} | **作者/UP主:** {author or '未知'}",
        "",
    ]

    kf_map = keyframes_map or {}

    for seg in merged_segments:
        start_fmt = format_timestamp(seg.start_seconds)
        end_fmt = format_timestamp(seg.end_seconds)
        lines.append(f"### [{start_fmt} - {end_fmt}]")
        lines.append("")

        for kf_time, rel_img_path in list(kf_map.items()):
            if seg.start_seconds <= kf_time <= seg.end_seconds:
                lines.append(f"![画面截图 {format_timestamp(kf_time)}]({rel_img_path})")
                lines.append("")

        if seg.speaker:
            lines.append(f"**{seg.speaker}:** {seg.text}")
        else:
            lines.append(seg.text)
        lines.append("")

    return "\n".join(lines).strip() + "\n"


async def publish_video_url_ingress(
    structure: WikiStructure,
    request: VideoUrlIngressRequest,
) -> ClipIngressResult:
    """Extract online video subtitles (Bilibili / YouTube) and ingest into Wiki."""
    url = request.url.strip()
    url_hash = hashlib.sha256(url.encode()).hexdigest()

    title = "Video Transcript"
    author = ""
    duration_str = ""
    platform = "video"
    raw_segments: list[MediaTranscriptSegment] = []

    if is_bilibili_url(url):
        platform = "bilibili"
        doc = await extract_bilibili_subtitle(url)
        if not doc:
            raise ValueError(f"无法获取 Bilibili 视频字幕或该视频未公开字幕: {url}")
        meta = doc.metadata
        title = str(meta.get("title", title))
        author = str(meta.get("author_name", ""))
        duration_str = str(meta.get("duration", ""))
        raw_segments = parse_transcript_text_to_segments(doc.page_content)
    elif "youtube.com" in url.lower() or "youtu.be" in url.lower():
        platform = "youtube"
        doc = await extract_youtube_transcript(
            url,
            preferred_languages=list(request.preferred_languages),
        )
        if not doc:
            raise ValueError(f"无法获取 YouTube 视频字幕或该视频未提供字幕: {url}")
        meta = doc.metadata
        title = str(meta.get("title", title))
        author = str(meta.get("author_name", ""))
        duration_str = str(meta.get("duration", ""))
        raw_segments = parse_transcript_text_to_segments(doc.page_content)
    else:
        raise ValueError(f"不支持的视频 URL 平台 (当前支持 Bilibili 与 YouTube): {url}")

    if not raw_segments:
        raise ValueError("提取到的字幕内容为空")

    merged = adaptive_merge_segments(
        raw_segments,
        window_duration_seconds=request.window_duration_seconds,
        window_max_chars=request.window_max_chars,
    )

    markdown_body = build_video_markdown(
        title=title,
        source_url=url,
        duration_str=duration_str,
        platform=platform,
        author=author,
        merged_segments=merged,
    )

    if request.filename.strip():
        fname = request.filename.strip()
        if not fname.endswith(".md"):
            fname = f"{fname}.md"
    else:
        fname = f"{_slugify(title, url_hash)}.md"

    folder = (
        WikiStructure._sanitize_path(request.folder_path.strip())
        if request.folder_path.strip()
        else "videos"
    )
    rel_path = f"{folder}/{fname}"

    conflict_policy = (
        request.conflict_policy
        if request.conflict_policy is not None
        else RawConflictPolicy.FAIL
    )

    try:
        pub_res = await publish_raw(
            structure,
            RawPublishRequest(
                relative_path=rel_path,
                content=markdown_body,
                conflict_policy=conflict_policy,
                supersede_reason=request.supersede_reason,
            ),
            caller=request.caller,
        )
    except RawGateError as exc:
        if exc.code == "raw_conflict":
            return ClipIngressResult(
                relative_path=rel_path,
                written=False,
                skipped=True,
                conflict=True,
                security_blocked=False,
            )
        if exc.code == "raw_security_blocked":
            return ClipIngressResult(
                relative_path=rel_path,
                written=False,
                skipped=False,
                conflict=False,
                security_blocked=True,
            )
        raise

    return ClipIngressResult(
        relative_path=rel_path,
        written=pub_res.written,
        skipped=pub_res.skipped,
        conflict=pub_res.conflict_skipped,
        security_blocked=pub_res.security_blocked,
        superseded=pub_res.superseded,
    )


async def publish_media_ingress(
    structure: WikiStructure,
    request: MediaIngressRequest,
) -> ClipIngressResult:
    """Ingest transcribed media segments and keyframes directly into Wiki."""
    title = request.title.strip() or Path(request.media_filename).stem or "Media Note"
    url_hash = hashlib.sha256(
        (request.source_url or request.media_filename).encode()
    ).hexdigest()

    asset_stats = IngressAssetStats()
    keyframes_map: dict[float, str] = {}

    for kf in request.keyframes:
        if not kf.image_bytes:
            continue
        fname = store_asset_bytes(
            structure,
            data=kf.image_bytes,
            content_type=kf.mime_type or "image/jpeg",
        )
        if fname:
            asset_stats = IngressAssetStats(
                stored=asset_stats.stored + 1,
                skipped=asset_stats.skipped,
                failed=asset_stats.failed,
            )
            raw_parts = len(Path(request.folder_path or "videos").parts)
            ups = [".."] * (raw_parts + 1)
            rel_img = "/".join([*ups, "wiki", "assets", fname])
            keyframes_map[kf.timestamp_seconds] = rel_img
        else:
            asset_stats = IngressAssetStats(
                stored=asset_stats.stored,
                skipped=asset_stats.skipped,
                failed=asset_stats.failed + 1,
            )

    if request.media_bytes:
        store_media_asset_bytes(
            structure,
            data=request.media_bytes,
            content_type="video/mp4",
        )

    merged = adaptive_merge_segments(request.segments)
    duration_str = (
        format_timestamp(request.duration_seconds)
        if request.duration_seconds > 0
        else ""
    )

    markdown_body = build_video_markdown(
        title=title,
        source_url=request.source_url or request.media_filename,
        duration_str=duration_str,
        platform="local" if not request.source_url else "web",
        author="",
        merged_segments=merged,
        keyframes_map=keyframes_map,
    )

    fname = f"{_slugify(title, url_hash)}.md"
    folder = (
        WikiStructure._sanitize_path(request.folder_path.strip())
        if request.folder_path.strip()
        else "videos"
    )
    rel_path = f"{folder}/{fname}"

    conflict_policy = (
        request.conflict_policy
        if request.conflict_policy is not None
        else RawConflictPolicy.FAIL
    )

    try:
        pub_res = await publish_raw(
            structure,
            RawPublishRequest(
                relative_path=rel_path,
                content=markdown_body,
                conflict_policy=conflict_policy,
                supersede_reason=request.supersede_reason,
            ),
            caller=request.caller,
        )
    except RawGateError as exc:
        if exc.code == "raw_conflict":
            return ClipIngressResult(
                relative_path=rel_path,
                written=False,
                skipped=True,
                conflict=True,
                security_blocked=False,
                asset_stats=asset_stats,
            )
        if exc.code == "raw_security_blocked":
            return ClipIngressResult(
                relative_path=rel_path,
                written=False,
                skipped=False,
                conflict=False,
                security_blocked=True,
                asset_stats=asset_stats,
            )
        raise

    return ClipIngressResult(
        relative_path=rel_path,
        written=pub_res.written,
        skipped=pub_res.skipped,
        conflict=pub_res.conflict_skipped,
        security_blocked=pub_res.security_blocked,
        asset_stats=asset_stats,
        superseded=pub_res.superseded,
    )
