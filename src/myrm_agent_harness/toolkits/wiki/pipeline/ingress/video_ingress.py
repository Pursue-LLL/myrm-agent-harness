"""Wiki video raw ingress (YouTube, Bilibili & local media transcripts) → publish_raw.

[INPUT]
- pipeline.raw_gate (POS: raw publication gate)
- toolkits.web_fetch.extractors (POS: YouTube & Bilibili transcript extractors)
- ingress.asset_store (POS: keyframes & media asset storage)
- ingress.video_segment_parser (POS: transcript parsing, window merging, markdown synthesis)

[OUTPUT]
- publish_video_url_ingress, publish_media_ingress, adaptive_merge_segments, format_timestamp, parse_timestamp_str

[POS]
Video & audio media raw ingress pipeline. Transforms timestamped video transcripts into structured Markdown with second-level timestamps and publishes to Raw Gate.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

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
    MediaTranscriptSegment,
    VideoUrlIngressRequest,
)
from myrm_agent_harness.toolkits.wiki.pipeline.ingress.video_segment_parser import (
    MergedVideoSegment,
    adaptive_merge_segments,
    build_video_markdown,
    format_timestamp,
    parse_timestamp_str,
    parse_transcript_text_to_segments,
    slugify_video_title,
)
from myrm_agent_harness.toolkits.wiki.pipeline.raw_gate import (
    RawConflictPolicy,
    RawGateError,
    RawPublishRequest,
    publish_raw,
)

logger = logging.getLogger(__name__)

__all__ = [
    "MergedVideoSegment",
    "adaptive_merge_segments",
    "build_video_markdown",
    "format_timestamp",
    "parse_timestamp_str",
    "parse_transcript_text_to_segments",
    "publish_media_ingress",
    "publish_video_url_ingress",
]


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
        fname = f"{slugify_video_title(title, url_hash)}.md"

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

    fname = f"{slugify_video_title(title, url_hash)}.md"
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
