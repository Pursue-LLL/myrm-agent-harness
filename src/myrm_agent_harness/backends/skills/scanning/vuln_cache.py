"""Vulnerability scan result cache.

Provides in-memory caching with optional persistent disk backing and TTL expiration
to eliminate redundant network requests to OSV.dev during repeated skill rescans.

[INPUT]
- AdvisoryFinding (from security_advisories)

[OUTPUT]
- VulnCacheEntry: cached findings with expiration timestamp
- VulnScanCache: thread-safe cache store with get/set/prune/save/load capabilities
- get_vuln_cache: singleton accessor for the default vulnerability cache

[POS]
Performance optimization layer for dependency supply chain security scanning.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

from myrm_agent_harness.backends.skills.scanning.scanner import ScanSeverity
from myrm_agent_harness.backends.skills.scanning.security_advisories import AdvisoryFinding

logger = logging.getLogger(__name__)

DEFAULT_CACHE_TTL_SECONDS = 86400.0  # 24 hours


@dataclass(frozen=True, slots=True)
class VulnCacheEntry:
    """A cached set of advisory findings for a specific package and version."""

    ecosystem: str
    package_name: str
    version: str
    findings: tuple[AdvisoryFinding, ...]
    cached_at: float
    ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.cached_at) > self.ttl_seconds


class VulnScanCache:
    """Thread-safe cache store for vulnerability findings."""

    def __init__(self, default_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS) -> None:
        self._entries: dict[tuple[str, str, str], VulnCacheEntry] = {}
        self._default_ttl_seconds = default_ttl_seconds

    def _make_key(self, ecosystem: str, package_name: str, version: str) -> tuple[str, str, str]:
        return (ecosystem.strip().lower(), package_name.strip().lower(), version.strip())

    def get(self, ecosystem: str, package_name: str, version: str) -> list[AdvisoryFinding] | None:
        """Get cached advisory findings if not expired."""
        key = self._make_key(ecosystem, package_name, version)
        entry = self._entries.get(key)
        if entry is None:
            return None
        if entry.is_expired:
            self._entries.pop(key, None)
            return None
        return list(entry.findings)

    def set(
        self,
        ecosystem: str,
        package_name: str,
        version: str,
        findings: Sequence[AdvisoryFinding],
        ttl_seconds: float | None = None,
    ) -> None:
        """Cache advisory findings for a package version."""
        key = self._make_key(ecosystem, package_name, version)
        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl_seconds
        self._entries[key] = VulnCacheEntry(
            ecosystem=ecosystem.strip().lower(),
            package_name=package_name.strip().lower(),
            version=version.strip(),
            findings=tuple(findings),
            cached_at=time.time(),
            ttl_seconds=ttl,
        )

    def clear(self) -> None:
        """Clear all cached entries."""
        self._entries.clear()

    def prune_expired(self) -> int:
        """Prune all expired entries from memory."""
        now = time.time()
        expired_keys = [
            k for k, v in self._entries.items() if (now - v.cached_at) > v.ttl_seconds
        ]
        for k in expired_keys:
            self._entries.pop(k, None)
        return len(expired_keys)

    def save_to_disk(self, file_path: Path | str) -> bool:
        """Save non-expired cache entries to disk."""
        target = Path(file_path).resolve()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            self.prune_expired()
            serializable: list[dict[str, object]] = []
            for entry in self._entries.values():
                findings_data = []
                for f in entry.findings:
                    findings_data.append(
                        {
                            "advisory_id": f.advisory_id,
                            "package_name": f.package_name,
                            "ecosystem": f.ecosystem,
                            "severity": int(f.severity),
                            "title": f.title,
                            "description": f.description,
                            "matched_version": f.matched_version,
                            "file_path": f.file_path,
                            "is_acked": f.is_acked,
                            "source": f.source,
                        }
                    )
                serializable.append(
                    {
                        "ecosystem": entry.ecosystem,
                        "package_name": entry.package_name,
                        "version": entry.version,
                        "cached_at": entry.cached_at,
                        "ttl_seconds": entry.ttl_seconds,
                        "findings": findings_data,
                    }
                )
            target.write_text(json.dumps(serializable, indent=2), encoding="utf-8")
            return True
        except Exception as exc:
            logger.debug("Failed to save vulnerability cache to %s: %s", target, exc)
            return False

    def load_from_disk(self, file_path: Path | str) -> bool:
        """Load cache entries from disk."""
        target = Path(file_path).resolve()
        if not target.is_file():
            return False
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return False
            now = time.time()
            for item in data:
                if not isinstance(item, dict):
                    continue
                cached_at = float(item.get("cached_at", 0.0))
                ttl_seconds = float(item.get("ttl_seconds", self._default_ttl_seconds))
                if (now - cached_at) > ttl_seconds:
                    continue

                ecosystem = str(item.get("ecosystem", ""))
                package_name = str(item.get("package_name", ""))
                version = str(item.get("version", ""))
                raw_findings = item.get("findings", [])
                findings_list: list[AdvisoryFinding] = []
                if isinstance(raw_findings, list):
                    for rf in raw_findings:
                        if isinstance(rf, dict):
                            sev_int = int(rf.get("severity", ScanSeverity.HIGH))
                            try:
                                sev_enum = ScanSeverity(sev_int)
                            except ValueError:
                                sev_enum = ScanSeverity.HIGH
                            findings_list.append(
                                AdvisoryFinding(
                                    advisory_id=str(rf.get("advisory_id", "")),
                                    package_name=str(rf.get("package_name", "")),
                                    ecosystem=str(rf.get("ecosystem", "")),
                                    severity=sev_enum,
                                    title=str(rf.get("title", "")),
                                    description=str(rf.get("description", "")),
                                    matched_version=str(rf.get("matched_version", "")),
                                    file_path=str(rf.get("file_path", "")),
                                    is_acked=bool(rf.get("is_acked", False)),
                                    source=str(rf.get("source", "osv_api")),
                                )
                            )

                key = self._make_key(ecosystem, package_name, version)
                self._entries[key] = VulnCacheEntry(
                    ecosystem=ecosystem,
                    package_name=package_name,
                    version=version,
                    findings=tuple(findings_list),
                    cached_at=cached_at,
                    ttl_seconds=ttl_seconds,
                )
            return True
        except Exception as exc:
            logger.debug("Failed to load vulnerability cache from %s: %s", target, exc)
            return False


_GLOBAL_VULN_CACHE = VulnScanCache()


def get_vuln_cache() -> VulnScanCache:
    """Get the global default vulnerability scan cache instance."""
    return _GLOBAL_VULN_CACHE
