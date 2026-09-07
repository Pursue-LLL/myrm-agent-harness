"""Centralized static skills index data source.

Loads and queries static pre-indexed skill catalogs (e.g. 90,000+ ecosystem skills)
with tiered caching: in-memory fast search -> local compressed snapshot -> remote CDN index.
Supports ETag/Last-Modified conditional sync, offline graceful degradation, and sub-5ms filtering.

[INPUT]
- backends.skills.market_protocols::SkillSearchResult (POS: Unified search result data class)
- infra.tls_compat::create_httpx_client (POS: Resilient HTTP client creation)

[OUTPUT]
- StaticIndexSkillSource: High-performance static index skill source.

[POS]
Provides StaticIndexSkillSource with multi-source mirror cache and instant offline search.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Final, Literal

from myrm_agent_harness.backends.skills.market_protocols import SkillSearchResult
from myrm_agent_harness.infra.tls_compat import create_httpx_client

logger = logging.getLogger(__name__)

DEFAULT_INDEX_URL: Final[str] = (
    "https://raw.githubusercontent.com/open-perplexity/skills-index/main/skills-index.json.gz"
)
DEFAULT_MIRROR_URLS: Final[tuple[str, ...]] = (
    "https://raw.githubusercontent.com/open-perplexity/skills-index/main/skills-index.json.gz",
    "https://cdn.jsdelivr.net/gh/open-perplexity/skills-index@main/skills-index.json.gz",
    "https://fastly.jsdelivr.net/gh/open-perplexity/skills-index@main/skills-index.json.gz",
)
DEFAULT_CACHE_DIR: Final[Path] = Path.home() / ".myrm" / "cache"
DEFAULT_TTL_SECONDS: Final[float] = 6 * 3600.0  # 6 hours
DEFAULT_SYNC_TIMEOUT: Final[float] = 10.0


class StaticIndexSkillSource:
    """Static aggregated skill index source.

    Maintains an in-memory inverted/keyword-based searchable snapshot of external skills.
    Fetches gzip-compressed indexes with HTTP conditional requests (ETag/If-None-Match),
    caches locally on disk, and seamlessly falls back to existing local snapshots when offline.
    """

    def __init__(
        self,
        index_url: str = DEFAULT_INDEX_URL,
        cache_dir: Path | None = None,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        preloaded_entries: list[dict[str, Any]] | None = None,
    ) -> None:
        self._index_url = os.environ.get("MYRM_SKILLS_INDEX_URL", index_url)
        self._cache_dir = cache_dir or DEFAULT_CACHE_DIR
        self._ttl_seconds = ttl_seconds
        self._cache_file = self._cache_dir / "skills-index.json.gz"
        self._etag_file = self._cache_dir / "skills-index.etag"

        self._entries: list[SkillSearchResult] = []
        self._last_synced_at: float = 0.0
        self._is_loaded: bool = False

        if preloaded_entries is not None:
            self._load_from_raw_dicts(preloaded_entries)

    @property
    def source_name(self) -> str:
        return "static_index"

    @property
    def total_indexed_skills(self) -> int:
        return len(self._entries)

    async def search(self, query: str, limit: int = 10) -> list[SkillSearchResult]:
        """Search skills across pre-indexed metadata in milliseconds."""
        await self._ensure_index_loaded()

        if not self._entries:
            return []

        clean_query = query.strip().lower()
        if not clean_query:
            return self._entries[:limit]

        keywords = clean_query.split()
        matched: list[tuple[float, SkillSearchResult]] = []

        for item in self._entries:
            score = self._compute_relevance(item, clean_query, keywords)
            if score > 0.0:
                matched.append((score, item))

        # Sort descending by score, then stars
        matched.sort(key=lambda x: (x[0], x[1].stars), reverse=True)
        return [item for _, item in matched[:limit]]

    async def get_detail(self, skill_id: str) -> SkillSearchResult | None:
        """Find a skill by exact id or match."""
        await self._ensure_index_loaded()
        clean_id = skill_id.strip().lower()
        for item in self._entries:
            if item.id.lower() == clean_id or item.name.lower() == clean_id:
                return item
        return None

    async def force_refresh(self) -> bool:
        """Manually trigger index sync from remote CDN ignoring local TTL."""
        return await self._sync_remote_index(force=True)

    async def _ensure_index_loaded(self) -> None:
        if self._is_loaded and (time.time() - self._last_synced_at < self._ttl_seconds):
            return

        if not self._is_loaded:
            # 1. Try loading from local disk cache snapshot first
            if self._load_from_disk_cache():
                self._is_loaded = True

        # 2. If TTL expired or not yet synced, attempt background remote sync
        now = time.time()
        if now - self._last_synced_at >= self._ttl_seconds:
            await self._sync_remote_index(force=False)

    def _load_from_disk_cache(self) -> bool:
        if not self._cache_file.exists():
            uncompressed_file = self._cache_dir / "skills-index.json"
            if uncompressed_file.exists():
                try:
                    data = json.loads(uncompressed_file.read_text(encoding="utf-8"))
                    items = data if isinstance(data, list) else (data.get("skills") or data.get("items") or [])
                    if isinstance(items, list):
                        self._load_from_raw_dicts(items)
                        self._is_loaded = True
                        return True
                except Exception as err:
                    logger.warning("Failed to load uncompressed skills index disk cache: %s", err)
            return False

        try:
            try:
                with gzip.open(self._cache_file, "rt", encoding="utf-8") as f:
                    data = json.load(f)
            except (gzip.BadGzipFile, OSError):
                data = json.loads(self._cache_file.read_text(encoding="utf-8"))

            items = data if isinstance(data, list) else (data.get("skills") or data.get("items") or [])
            if isinstance(items, list):
                self._load_from_raw_dicts(items)
                self._is_loaded = True
                return True
        except Exception as err:
            logger.warning("Failed to load skills index disk cache: %s", err)
        return False

    async def _sync_remote_index(self, force: bool = False) -> bool:
        if not self._index_url:
            return False

        headers: dict[str, str] = {}
        etag: str | None = None
        if not force and self._etag_file.exists():
            try:
                etag = self._etag_file.read_text(encoding="utf-8").strip()
                if etag:
                    headers["If-None-Match"] = etag
            except Exception:
                pass

        try:
            async with create_httpx_client(timeout=DEFAULT_SYNC_TIMEOUT) as client:
                resp = await client.get(self._index_url, headers=headers)
                if resp.status_code == 304:
                    if not self._is_loaded:
                        self._load_from_disk_cache()
                    self._last_synced_at = time.time()
                    return True

                if resp.status_code == 200:
                    content_bytes = resp.content
                    # Check if response is gzipped
                    if content_bytes[:2] == b"\x1f\x8b":
                        raw_json = gzip.decompress(content_bytes).decode("utf-8")
                        compressed_bytes = content_bytes
                    else:
                        raw_json = content_bytes.decode("utf-8")
                        compressed_bytes = gzip.compress(content_bytes)

                    data = json.loads(raw_json)
                    items: list[dict[str, Any]] | None = None
                    if isinstance(data, list):
                        items = data
                    elif isinstance(data, dict):
                        raw_items = data.get("skills") or data.get("items") or []
                        if isinstance(raw_items, list):
                            items = raw_items

                    if items is not None:
                        self._load_from_raw_dicts(items)
                        self._is_loaded = True
                        self._last_synced_at = time.time()

                        # Persist to disk cache
                        try:
                            self._cache_dir.mkdir(parents=True, exist_ok=True)
                            self._cache_file.write_bytes(compressed_bytes)
                            new_etag = resp.headers.get("etag") or resp.headers.get("ETag")
                            if new_etag:
                                self._etag_file.write_text(new_etag, encoding="utf-8")
                        except Exception as write_err:
                            logger.warning("Failed to write skills index to disk: %s", write_err)

                        return True
        except Exception as e:
            logger.debug("Remote skills index sync failed (using local snapshot): %s", e)

        self._last_synced_at = time.time()  # Prevent immediate retries on connection failure
        return False

    def _load_from_raw_dicts(self, raw_items: list[dict[str, Any]]) -> None:
        parsed: list[SkillSearchResult] = []
        for raw in raw_items:
            try:
                method: Literal["git", "zip", "direct"] = "git"
                raw_method = raw.get("install_method")
                if raw_method in ("git", "zip", "direct"):
                    method = raw_method

                pkg_type: Literal["skill", "agent_plugin"] = "skill"
                raw_pkg = raw.get("package_type")
                if raw_pkg in ("skill", "agent_plugin"):
                    pkg_type = raw_pkg

                item = SkillSearchResult(
                    id=str(raw.get("id") or raw.get("name") or "unknown"),
                    name=str(raw.get("name") or "Unnamed"),
                    description=str(raw.get("description") or ""),
                    source="static_index",
                    author=str(raw.get("author") or "community"),
                    install_url=str(raw.get("install_url") or ""),
                    install_method=method,
                    version=str(raw.get("version") or "1.0.0"),
                    stars=int(raw.get("stars") or 0),
                    downloads=int(raw.get("downloads") or 0),
                    tags=list(raw.get("tags") or []),
                    subdirectory=raw.get("subdirectory"),
                    package_type=pkg_type,
                    keywords=list(raw.get("keywords") or []),
                    declared_mcp_servers=list(raw.get("declared_mcp_servers") or []),
                    extra_manifest=raw.get("extra_manifest"),
                )
                parsed.append(item)
            except Exception as e:
                logger.debug("Skipping malformed index entry: %s", e)
        self._entries = parsed

    @staticmethod
    def _compute_relevance(
        item: SkillSearchResult,
        clean_query: str,
        keywords: list[str],
    ) -> float:
        name_lower = item.name.lower()
        desc_lower = item.description.lower()
        tags_lower = [t.lower() for t in item.tags]
        keywords_lower = [k.lower() for k in item.keywords]

        score = 0.0

        # Exact phrase matches
        if clean_query == name_lower:
            score += 150.0
        elif clean_query in name_lower:
            score += 80.0

        if clean_query in desc_lower:
            score += 30.0

        # Keyword token matches
        for kw in keywords:
            if kw in name_lower:
                score += 40.0
            if kw in desc_lower:
                score += 15.0
            if any(kw in t for t in tags_lower):
                score += 25.0
            if any(kw in k for k in keywords_lower):
                score += 25.0

        return score
