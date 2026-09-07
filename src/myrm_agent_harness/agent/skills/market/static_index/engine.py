"""Centralized Static Skills Index & Local Mirror Cache Engine.

[INPUT]
- types::StaticSkillItem, StaticIndexManifest
- backends.skills.market_protocols::SkillSearchResult

[OUTPUT]
- StaticSkillsIndexManager: syncs index from CDN/static URL with ETag/gzip, caches locally, provides sub-millisecond in-memory search

[POS]
High-performance local skill index mirroring engine for Myrm Skill Market.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import time
from pathlib import Path

from myrm_agent_harness.agent.skills.market.static_index.types import (
    StaticIndexManifest,
    StaticSkillItem,
)
from myrm_agent_harness.backends.skills.market_protocols import SkillSearchResult
from myrm_agent_harness.infra.tls_compat import create_httpx_client

logger = logging.getLogger(__name__)

DEFAULT_STATIC_INDEX_URL = "https://cdn.myrm.ai/skills/skills-index.json.gz"
DEFAULT_CACHE_TTL_SECONDS = 6 * 3600  # 6 hours
DEFAULT_LOCAL_CACHE_DIR = Path.home() / ".myrm" / "cache"


class StaticSkillsIndexManager:
    """Manages local mirror cache of centralized static skills index."""

    def __init__(
        self,
        index_url: str = DEFAULT_STATIC_INDEX_URL,
        cache_dir: Path | None = None,
        ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
    ) -> None:
        self.index_url = index_url
        self.cache_dir = cache_dir or DEFAULT_LOCAL_CACHE_DIR
        self.ttl_seconds = ttl_seconds
        self._skills_map: dict[str, StaticSkillItem] = {}
        self._manifest: StaticIndexManifest | None = None
        self._last_sync_time: float = 0.0
        self._etag: str = ""

    @property
    def total_skills(self) -> int:
        return len(self._skills_map)

    @property
    def is_stale(self) -> bool:
        return (time.time() - self._last_sync_time) > self.ttl_seconds

    def get_cache_file_path(self) -> Path:
        return self.cache_dir / "skills-index.json"

    def get_etag_file_path(self) -> Path:
        return self.cache_dir / "skills-index.etag"

    def load_local_cache(self) -> bool:
        """Load static index from local filesystem cache."""
        cache_file = self.get_cache_file_path()
        etag_file = self.get_etag_file_path()

        if not cache_file.exists():
            return False

        try:
            content = cache_file.read_text(encoding="utf-8")
            data = json.loads(content)
            skills_raw = data.get("skills", [])
            items: dict[str, StaticSkillItem] = {}
            for item_dict in skills_raw:
                item = StaticSkillItem.from_dict(item_dict)
                items[item.id] = item

            self._skills_map = items
            self._manifest = StaticIndexManifest(
                version=str(data.get("version", "1.0")),
                updated_at=str(data.get("updated_at", "")),
                total_skills=len(items),
                skills=list(items.values()),
            )
            if etag_file.exists():
                self._etag = etag_file.read_text(encoding="utf-8").strip()

            self._last_sync_time = cache_file.stat().st_mtime
            logger.info("Loaded %d static skills from local cache %s", len(items), cache_file)
            return True
        except Exception as e:
            logger.warning("Failed to load local skills index cache: %s", e)
            return False

    def save_local_cache(self, raw_json: str, etag: str = "") -> None:
        """Persist static index JSON and ETag to local cache directory."""
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file = self.get_cache_file_path()
            etag_file = self.get_etag_file_path()

            cache_file.write_text(raw_json, encoding="utf-8")
            if etag:
                etag_file.write_text(etag, encoding="utf-8")
                self._etag = etag
            self._last_sync_time = time.time()
        except Exception as e:
            logger.warning("Failed to save local skills index cache: %s", e)

    async def sync_remote_index(self, force: bool = False, timeout: float = 10.0) -> bool:
        """Fetch remote skills index with ETag / conditional GET and gzip support."""
        if not force and not self.is_stale and self._skills_map:
            return True

        headers: dict[str, str] = {
            "Accept": "application/json, application/gzip",
            "Accept-Encoding": "gzip, deflate",
        }
        if self._etag and not force:
            headers["If-None-Match"] = self._etag

        try:
            async with create_httpx_client(timeout=timeout) as client:
                resp = await client.get(self.index_url, headers=headers)
                if resp.status_code == 304:
                    self._last_sync_time = time.time()
                    logger.debug("Static skills index not modified (304)")
                    return True

                if resp.status_code != 200:
                    logger.warning("Failed to fetch static skills index: status %d", resp.status_code)
                    return False

                # Handle raw gzip stream if returned as binary
                content_bytes = resp.content
                if content_bytes.startswith(b"\x1f\x8b"):
                    decompressed = gzip.decompress(content_bytes)
                    json_str = decompressed.decode("utf-8")
                else:
                    json_str = resp.text

                data = json.loads(json_str)
                skills_raw = data.get("skills", [])
                items: dict[str, StaticSkillItem] = {}
                for item_dict in skills_raw:
                    item = StaticSkillItem.from_dict(item_dict)
                    items[item.id] = item

                self._skills_map = items
                new_etag = resp.headers.get("ETag", "").strip()
                self.save_local_cache(json_str, etag=new_etag)
                logger.info("Successfully synced %d static skills from %s", len(items), self.index_url)
                return True
        except Exception as e:
            logger.warning("Static skills index sync error: %s", e)
            return False

    def search(
        self,
        query: str,
        limit: int = 20,
        source_filter: str = "",
        tag_filter: str = "",
    ) -> list[SkillSearchResult]:
        """Sub-millisecond in-memory token and prefix matching."""
        if not query and not source_filter and not tag_filter:
            # Browse mode: return top rated skills
            all_items = list(self._skills_map.values())
            all_items.sort(key=lambda s: (-s.stars, -s.downloads, s.name))
            return [self._to_search_result(s) for s in all_items[:limit]]

        q_terms = [t.lower() for t in query.strip().split() if t.strip()]
        results: list[tuple[float, StaticSkillItem]] = []

        for item in self._skills_map.values():
            if source_filter and item.source.lower() != source_filter.lower():
                continue
            if tag_filter and tag_filter.lower() not in [t.lower() for t in item.tags]:
                continue

            score = 0.0
            name_lower = item.name.lower()
            desc_lower = item.description.lower()
            id_lower = item.id.lower()

            match_all = True
            for term in q_terms:
                if term in name_lower:
                    score += 10.0 if name_lower.startswith(term) else 5.0
                elif term in id_lower:
                    score += 4.0
                elif term in desc_lower:
                    score += 2.0
                elif any(term in t.lower() for t in item.tags):
                    score += 3.0
                else:
                    match_all = False
                    break

            if match_all and (score > 0 or not q_terms):
                score += min(item.stars / 100.0, 5.0)
                score += min(item.downloads / 1000.0, 3.0)
                results.append((score, item))

        results.sort(key=lambda x: -x[0])
        return [self._to_search_result(item) for _, item in results[:limit]]

    def get_skill(self, skill_id: str) -> StaticSkillItem | None:
        """Lookup skill directly by ID."""
        return self._skills_map.get(skill_id)

    @staticmethod
    def _to_search_result(item: StaticSkillItem) -> SkillSearchResult:
        return SkillSearchResult(
            id=item.id,
            name=item.name,
            description=item.description,
            source=item.source,
            version=item.version,
            author=item.author,
            stars=item.stars,
            downloads=item.downloads,
            tags=item.tags,
            install_url=item.install_url,
            install_method=item.install_method,
            subdirectory=item.subdirectory,
        )
