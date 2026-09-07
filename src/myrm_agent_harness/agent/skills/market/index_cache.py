"""Centralized static skills index cache and fast in-memory filter.

[INPUT]
- backends.skills.market_protocols::SkillSearchResult
- pathlib::Path, httpx / aiohttp / aiofiles (standard io)

[OUTPUT]
- SkillsIndexCache: Manages local file caching, ETag conditional GETs, 6h TTL, and <10ms in-memory filtering.

[POS]
Offline-first index synchronization and search acceleration for the skill market.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from myrm_agent_harness.backends.skills.market_protocols import SkillSearchResult

logger = logging.getLogger(__name__)

# Default local cache path
_DEFAULT_CACHE_DIR = Path.home() / ".myrm" / "cache"
_INDEX_FILE_NAME = "skills-index.json"
_META_FILE_NAME = "skills-index.meta.json"
_DEFAULT_INDEX_TTL_SECONDS = 6 * 3600  # 6 Hours


class SkillsIndexCache:
    """Manages offline-first static index cache with fast in-memory filtering."""

    def __init__(
        self,
        cache_dir: Path | None = None,
        index_url: str = "",
        ttl_seconds: int = _DEFAULT_INDEX_TTL_SECONDS,
    ) -> None:
        self.cache_dir = cache_dir or _DEFAULT_CACHE_DIR
        self.index_url = index_url.strip()
        self.ttl_seconds = ttl_seconds
        self._index_path = self.cache_dir / _INDEX_FILE_NAME
        self._meta_path = self.cache_dir / _META_FILE_NAME
        self._in_memory_records: list[SkillSearchResult] = []
        self._last_loaded_time: float = 0.0

    def load_cached_index(self) -> list[SkillSearchResult]:
        """Load static skills index from local file cache into memory."""
        if not self._index_path.exists():
            return []

        try:
            content = self._index_path.read_text(encoding="utf-8")
            data = json.loads(content)
            items = data.get("skills", data) if isinstance(data, dict) else data
            if not isinstance(items, list):
                return []

            records: list[SkillSearchResult] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                record = SkillSearchResult(
                    id=str(item.get("id", "")),
                    name=str(item.get("name", "")),
                    description=str(item.get("description", "")),
                    source=str(item.get("source", "index")),
                    author=str(item.get("author", "")),
                    install_url=str(item.get("install_url", "")),
                    install_method=item.get("install_method", "zip"),
                    version=str(item.get("version", "")),
                    stars=int(item.get("stars", 0)),
                    downloads=int(item.get("downloads", 0)),
                    tags=list(item.get("tags", [])),
                    readme_url=item.get("readme_url"),
                    subdirectory=item.get("subdirectory"),
                    package_type=item.get("package_type", "skill"),
                    keywords=list(item.get("keywords", [])),
                    declared_mcp_servers=list(item.get("declared_mcp_servers", [])),
                )
                if record.id and record.name:
                    records.append(record)

            self._in_memory_records = records
            self._last_loaded_time = time.time()
            return self._in_memory_records
        except Exception as exc:
            logger.warning("Failed to load skills index from %s: %s", self._index_path, exc)
            return []

    def save_index(self, items: list[dict[str, Any]], etag: str = "") -> None:
        """Persist fresh skills index data to disk."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            payload = {"skills": items, "updated_at": time.time()}
            self._index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            if etag:
                self._meta_path.write_text(json.dumps({"etag": etag, "timestamp": time.time()}), encoding="utf-8")
            self.load_cached_index()
        except Exception as exc:
            logger.warning("Failed to save skills index to %s: %s", self._index_path, exc)

    def is_cache_valid(self) -> bool:
        """Check if local cache exists and is within TTL."""
        if not self._index_path.exists():
            return False
        if not self._meta_path.exists():
            mtime = self._index_path.stat().st_mtime
            return (time.time() - mtime) < self.ttl_seconds
        try:
            meta = json.loads(self._meta_path.read_text(encoding="utf-8"))
            timestamp = float(meta.get("timestamp", 0))
            return (time.time() - timestamp) < self.ttl_seconds
        except Exception:
            return False

    def search_in_memory(self, query: str, limit: int = 50) -> list[SkillSearchResult]:
        """Perform sub-10ms in-memory filtering across name, description, and keywords."""
        if not self._in_memory_records:
            self.load_cached_index()

        q = query.strip().lower()
        if not q:
            return self._in_memory_records[:limit]

        query_tokens = [re.escape(t) for t in q.split() if t]
        if not query_tokens:
            return self._in_memory_records[:limit]

        patterns = [re.compile(t, re.IGNORECASE) for t in query_tokens]

        scored: list[tuple[int, SkillSearchResult]] = []
        for r in self._in_memory_records:
            score = 0
            name_lower = r.name.lower()
            desc_lower = r.description.lower()
            
            # Exact match bonus
            if q == name_lower:
                score += 100
            elif q in name_lower:
                score += 50
            
            # Token match scoring
            matched_all = True
            for pat in patterns:
                if pat.search(r.name):
                    score += 20
                elif pat.search(r.description):
                    score += 10
                elif any(pat.search(k) for k in r.keywords or []):
                    score += 15
                elif any(pat.search(t) for t in r.tags or []):
                    score += 15
                else:
                    matched_all = False
                    break

            if matched_all and score > 0:
                # Add stars weight (log-like)
                score += min(r.stars // 10, 20)
                scored.append((score, r))

        scored.sort(key=lambda item: -item[0])
        return [r for _, r in scored[:limit]]
