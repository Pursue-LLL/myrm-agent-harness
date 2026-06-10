"""YouTube transcript extractor.

Extracts subtitles/transcripts from YouTube videos via the youtube-transcript-api
library. Used as a fast-path shortcut in CrawlEngine when a YouTube URL is detected,
bypassing the three-tier HTML fetcher pipeline (which cannot access subtitle data).

Design pattern: analogous to binary_router.py — special content source routing.

[INPUT]
- (none — standalone module)

[OUTPUT]
- is_youtube_url: Check if a URL is a YouTube video URL
- extract_youtube_transcript: Extract transcript and return as Document

[POS]
YouTube transcript extractor. Fast-path content extraction for YouTube URLs,
returning timestamped Markdown Documents with video metadata.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING

from langchain_core.documents import Document

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.browser.pool.proxy import ProxyPool

logger = logging.getLogger(__name__)

_YOUTUBE_URL_RE = re.compile(
    r"(?:https?://)"
    r"(?:[\w-]+\.)*"
    r"(?:youtube\.com/(?:watch\?.*v=|shorts/|embed/|live/)"
    r"|youtu\.be/)"
    r"([a-zA-Z0-9_-]{11})",
)

_DEFAULT_LANGUAGES = ["en", "zh-Hans", "zh-Hant", "ja", "ko", "de", "fr", "es", "pt", "ru"]


def is_youtube_url(url: str) -> bool:
    """Check if a URL points to a YouTube video."""
    return _YOUTUBE_URL_RE.search(url) is not None


def _extract_video_id(url: str) -> str | None:
    """Extract the 11-character video ID from a YouTube URL."""
    match = _YOUTUBE_URL_RE.search(url)
    return match.group(1) if match else None


def _format_timestamp(seconds: float) -> str:
    """Convert seconds to HH:MM:SS or MM:SS."""
    total = int(seconds)
    h, remainder = divmod(total, 3600)
    m, s = divmod(remainder, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


async def extract_youtube_transcript(
    url: str,
    *,
    preferred_languages: list[str] | None = None,
    proxy_pool: ProxyPool | None = None,
) -> Document | None:
    """Extract YouTube video transcript and return as a Document.

    Args:
        url: YouTube video URL
        preferred_languages: Ordered list of preferred subtitle languages
        proxy_pool: Optional proxy pool for regions where YouTube is blocked

    Returns:
        Document with timestamped transcript as page_content and video metadata,
        or None if transcript is unavailable.
    """
    video_id = _extract_video_id(url)
    if not video_id:
        logger.warning("Failed to extract video ID from URL: %s", url[:100])
        return None

    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        logger.error("youtube-transcript-api not installed. Run: pip install youtube-transcript-api")
        return None

    languages = preferred_languages or _DEFAULT_LANGUAGES

    yt_proxy_config = None
    if proxy_pool:
        from youtube_transcript_api.proxies import GenericProxyConfig

        proxy_config = proxy_pool.get_next()
        proxy_url = proxy_config.to_url()
        yt_proxy_config = GenericProxyConfig(https_url=proxy_url)

    try:
        api = YouTubeTranscriptApi(proxy_config=yt_proxy_config)
        segments = await asyncio.to_thread(api.fetch, video_id, languages=languages)
    except Exception as e:
        error_msg = str(e).lower()
        if "disabled" in error_msg or "no transcript" in error_msg:
            logger.info("No transcript available for video %s: %s", video_id, e)
        else:
            logger.warning("YouTube transcript fetch failed for %s: %s", video_id, e)
        return None

    if not segments:
        logger.info("Empty transcript returned for video %s", video_id)
        return None

    timestamped_lines = [f"{_format_timestamp(seg.start)} {seg.text}" for seg in segments]
    full_text = "\n".join(timestamped_lines)

    last_seg = segments[-1]
    duration_seconds = last_seg.start + last_seg.duration
    duration_str = _format_timestamp(duration_seconds)

    metadata: dict[str, str | int | float] = {
        "url": url,
        "source_type": "youtube_transcript",
        "video_id": video_id,
        "duration": duration_str,
        "segment_count": len(segments),
    }

    return Document(page_content=full_text, metadata=metadata)
