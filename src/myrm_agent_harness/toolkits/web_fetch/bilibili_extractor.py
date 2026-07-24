"""Bilibili subtitle extractor.

Extracts subtitles from Bilibili videos via public API. Used as a fast-path
shortcut in FetchEngine when a Bilibili URL is detected, bypassing the
three-tier HTML fetcher pipeline.

Bilibili subtitles are loaded asynchronously via a separate API and are NOT
present in the page DOM, so Browser-based crawling cannot retrieve them.
This extractor is the only way to obtain Bilibili video subtitles.

When the API call fails or no subtitle is available, FetchEngine falls back
to standard HTML crawl (which provides title/description but no subtitles).

Design pattern: analogous to youtube_extractor.py — special content source routing.

[INPUT]
- (none — standalone module; uses only stdlib urllib + json)

[OUTPUT]
- is_bilibili_url: Check if a URL is a Bilibili video URL
- extract_bilibili_subtitle: Extract subtitle and return as Document, or None

[POS]
Bilibili subtitle fast-path extractor. Returns timestamped Markdown Documents
with video metadata (title, author, duration) via Bilibili public API; returns
None for Browser fallback when subtitle unavailable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.request
from typing import TYPE_CHECKING

from langchain_core.documents import Document

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.browser.pool.proxy import ProxyPool

logger = logging.getLogger(__name__)

_BILIBILI_URL_RE = re.compile(
    r"(?:https?://)"
    r"(?:www\.|m\.)?"
    r"bilibili\.com/video/"
    r"(BV[a-zA-Z0-9]{10}|av\d+)",
)

_BILIBILI_SHORT_URL_RE = re.compile(
    r"(?:https?://)"
    r"b23\.tv/"
    r"([a-zA-Z0-9]+)",
)

_VIEW_API = "https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
_PLAYER_API = "https://api.bilibili.com/x/player/v2?bvid={bvid}&cid={cid}"
_REQUEST_TIMEOUT = 8
_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://www.bilibili.com",
}


def is_bilibili_url(url: str) -> bool:
    """Check if a URL points to a Bilibili video."""
    return _BILIBILI_URL_RE.search(url) is not None or _BILIBILI_SHORT_URL_RE.search(url) is not None


def _extract_bvid(url: str) -> str | None:
    """Extract BV ID from a Bilibili URL."""
    match = _BILIBILI_URL_RE.search(url)
    if match:
        video_id = match.group(1)
        if video_id.startswith("BV"):
            return video_id
        return None
    return None


def _format_timestamp(seconds: float) -> str:
    """Convert seconds to HH:MM:SS or MM:SS."""
    total = int(seconds)
    h, remainder = divmod(total, 3600)
    m, s = divmod(remainder, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _build_opener(proxy_pool: ProxyPool | None = None) -> urllib.request.OpenerDirector:
    """Build urllib opener with optional proxy support."""
    if proxy_pool:
        proxy_config = proxy_pool.get_next()
        proxy_url = proxy_config.to_url()
        handler = urllib.request.ProxyHandler({"https": proxy_url, "http": proxy_url})
        return urllib.request.build_opener(handler)
    return urllib.request.build_opener()


def _api_request(url: str, opener: urllib.request.OpenerDirector, cookies: dict[str, str] | None = None) -> dict:
    """Make an API request to Bilibili and return parsed JSON."""
    headers = dict(_DEFAULT_HEADERS)
    if cookies:
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        headers["Cookie"] = cookie_str

    req = urllib.request.Request(url, headers=headers)
    with opener.open(req, timeout=_REQUEST_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


async def _fetch_video_metadata(
    bvid: str,
    opener: urllib.request.OpenerDirector,
) -> dict[str, str | int] | None:
    """Fetch video metadata (title, author, cid, duration) via Bilibili view API."""

    def _do_fetch() -> dict[str, str | int] | None:
        try:
            data = _api_request(_VIEW_API.format(bvid=bvid), opener)
            if data.get("code") != 0:
                logger.info("Bilibili view API returned code %s for %s", data.get("code"), bvid)
                return None
            video_data = data["data"]
            return {
                "title": video_data.get("title", ""),
                "author_name": video_data.get("owner", {}).get("name", ""),
                "cid": video_data.get("cid", 0),
                "duration": video_data.get("duration", 0),
                "bvid": bvid,
            }
        except Exception as exc:
            logger.debug("Bilibili metadata fetch failed for %s: %s", bvid, exc)
            return None

    return await asyncio.to_thread(_do_fetch)


async def _fetch_subtitle(
    bvid: str,
    cid: int,
    opener: urllib.request.OpenerDirector,
    cookies: dict[str, str] | None = None,
) -> list[dict[str, float | str]] | None:
    """Fetch subtitle segments from Bilibili player API.

    Tries to get CC subtitles first (no login needed for some videos),
    then AI-generated subtitles (requires login cookie).
    """

    def _do_fetch() -> list[dict[str, float | str]] | None:
        try:
            data = _api_request(
                _PLAYER_API.format(bvid=bvid, cid=cid),
                opener,
                cookies=cookies,
            )
            if data.get("code") != 0:
                logger.debug("Bilibili player API returned code %s for %s", data.get("code"), bvid)
                return None

            subtitles = data.get("data", {}).get("subtitle", {}).get("subtitles", [])
            if not subtitles:
                return None

            subtitle_url = subtitles[0].get("subtitle_url", "")
            if not subtitle_url:
                return None

            if subtitle_url.startswith("//"):
                subtitle_url = "https:" + subtitle_url

            subtitle_data = _api_request(subtitle_url, opener, cookies=cookies)
            body = subtitle_data.get("body", [])
            if not body:
                return None

            return body
        except Exception as exc:
            logger.debug("Bilibili subtitle fetch failed for %s: %s", bvid, exc)
            return None

    return await asyncio.to_thread(_do_fetch)


async def extract_bilibili_subtitle(
    url: str,
    *,
    cookies: dict[str, str] | None = None,
    proxy_pool: ProxyPool | None = None,
) -> Document | None:
    """Extract Bilibili video subtitle and return as a Document.

    Args:
        url: Bilibili video URL
        cookies: Optional bilibili.com cookies from SessionVault for AI subtitle access
        proxy_pool: Optional proxy pool

    Returns:
        Document with timestamped subtitle as page_content and video metadata,
        or None if subtitle is unavailable (triggers Browser fallback).
    """
    bvid = _extract_bvid(url)
    if not bvid:
        logger.debug("Failed to extract BV ID from URL: %s", url[:100])
        return None

    opener = _build_opener(proxy_pool)

    metadata_result = await _fetch_video_metadata(bvid, opener)
    if not metadata_result:
        return None

    cid = int(metadata_result["cid"])
    if cid == 0:
        return None

    segments = await _fetch_subtitle(bvid, cid, opener, cookies=cookies)
    if not segments:
        return None

    timestamped_lines = [
        f"{_format_timestamp(seg.get('from', 0))} {seg.get('content', '')}"
        for seg in segments
    ]
    full_text = "\n".join(timestamped_lines)

    duration = int(metadata_result.get("duration", 0))
    duration_str = _format_timestamp(duration) if duration > 0 else ""

    doc_metadata: dict[str, str | int | float] = {
        "url": url,
        "source_type": "bilibili_subtitle",
        "bvid": bvid,
        "segment_count": len(segments),
    }
    if metadata_result.get("title"):
        doc_metadata["title"] = str(metadata_result["title"])
    if metadata_result.get("author_name"):
        doc_metadata["author_name"] = str(metadata_result["author_name"])
    if duration_str:
        doc_metadata["duration"] = duration_str

    return Document(page_content=full_text, metadata=doc_metadata)
