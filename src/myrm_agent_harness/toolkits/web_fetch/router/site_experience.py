"""Site experience store——prompt-layer domain-level learning

Responsibilities:
- Stores site experiences accumulated by the Agent during browser operations（platform characteristics, URL rules, pitfalls, success flows）
- Cross-validates experience validity with DomainMetrics（code-layer learning validates prompt-layer experience）
- Auto-injection mechanism：BrowserSession.navigate() provides key experience at navigation time

Architecture:
- Independent from DomainMetrics storage (very different update frequencies: DomainMetrics per-request vs SiteExperience occasional)
- Reuses DomainMetricsManager storage path strategy
- LRU eviction (max 1000 domains)

[INPUT]
- (none)

[OUTPUT]
- SiteExperience: Site experience for a single domain (includes `prefer_http3` for L1 QUIC routing)
- SiteExperienceStore: Site experience store
- get_global_site_experience_store: Get global site experience store (singleton)

[POS]
Site experience store——prompt-layer domain-level learning
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .domain_metrics import DomainMetricsManager

logger = logging.getLogger(__name__)

_STALE_RECENT_FAILURE_THRESHOLD = 3
_MAX_DOMAINS = 1000

_global_site_experience_store: SiteExperienceStore | None = None


def get_global_site_experience_store() -> SiteExperienceStore:
    """Get global site experience store (singleton)"""
    global _global_site_experience_store
    if _global_site_experience_store is None:
        _global_site_experience_store = SiteExperienceStore()
    return _global_site_experience_store


@dataclass
class SiteExperience:
    """Site experience for a single domain"""

    domain: str
    platform_features: list[str] = field(default_factory=list)
    url_patterns: dict[str, str] = field(default_factory=dict)
    known_traps: list[str] = field(default_factory=list)
    successful_flows: list[str] = field(default_factory=list)
    prefer_http3: bool = False
    last_verified: str = ""
    verification_count: int = 0
    last_access: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, str | int | float | list[str] | dict[str, str] | bool]:
        """Serialize to JSON-storable dict"""
        return {
            "domain": self.domain,
            "platform_features": self.platform_features,
            "url_patterns": self.url_patterns,
            "known_traps": self.known_traps,
            "successful_flows": self.successful_flows,
            "prefer_http3": self.prefer_http3,
            "last_verified": self.last_verified,
            "verification_count": self.verification_count,
            "last_access": self.last_access,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str | int | float | list[str] | dict[str, str] | bool]) -> SiteExperience:
        """Deserialize from dict"""
        return cls(
            domain=str(data["domain"]),
            platform_features=list(data.get("platform_features", [])),
            url_patterns=dict(data.get("url_patterns", {})),
            known_traps=list(data.get("known_traps", [])),
            successful_flows=list(data.get("successful_flows", [])),
            prefer_http3=bool(data.get("prefer_http3", False)),
            last_verified=str(data.get("last_verified", "")),
            verification_count=int(data.get("verification_count", 0)),
            last_access=float(data.get("last_access", time.time())),
        )

    def is_empty(self) -> bool:
        """Whether experience is empty (no valid content)"""
        return (
            not self.platform_features and not self.url_patterns and not self.known_traps and not self.successful_flows
        )

    def format_for_injection(self, possibly_stale: bool = False) -> str:
        """Format as injection text (concise, for tool return value)

        Only includes the most useful known_traps and successful_flows at execution time。
        """
        parts: list[str] = [f"[Site experience for {self.domain}]"]

        if possibly_stale:
            parts.append(" This experience may be stale (recent success rate dropped).")

        if self.known_traps:
            parts.append("Known traps: " + "; ".join(self.known_traps))

        if self.successful_flows:
            parts.append("Successful approaches: " + "; ".join(self.successful_flows))

        return " | ".join(parts)

    def format_full(self, possibly_stale: bool = False) -> str:
        """Format as full query result (used before Agent decision-making)"""
        parts: list[str] = [f"[Site experience for {self.domain}]"]

        if possibly_stale:
            parts.append(" This experience may be stale (recent success rate dropped). Use with caution.")

        if self.platform_features:
            parts.append("Platform: " + "; ".join(self.platform_features))

        if self.url_patterns:
            patterns = [f"{k}: {v}" for k, v in self.url_patterns.items()]
            parts.append("URL patterns: " + "; ".join(patterns))

        if self.known_traps:
            parts.append("Known traps: " + "; ".join(self.known_traps))

        if self.successful_flows:
            parts.append("Successful approaches: " + "; ".join(self.successful_flows))

        if self.last_verified:
            parts.append(f"Last verified: {self.last_verified} (verified {self.verification_count} times)")

        return "\n".join(parts)


class SiteExperienceStore:
    """Site experience store

    Core capabilities:
    - Domain-level experience CRUD (auto-normalizes domains, strips www. prefix)
    - Cross-validates with DomainMetrics (detects potentially stale experience)
    - JSON persistence (separate file from DomainMetrics)
    - LRU eviction (max 1000 domains)

    Concurrency model:
    - threading.RLock protects in-memory data structures
    """

    @staticmethod
    def _normalize_domain(domain: str) -> str:
        """Normalize domain: lowercase + strip www. prefix"""
        d = domain.lower().strip()
        if d.startswith("www."):
            d = d[4:]
        return d

    def __init__(
        self,
        *,
        storage_path: str | Path | None = None,
        max_domains: int = _MAX_DOMAINS,
    ):
        self._storage_path = self._resolve_storage_path(storage_path)
        self._max_domains = max_domains
        self._lock = threading.RLock()
        self._experiences: dict[str, SiteExperience] = {}
        self._dirty = False

        self._load()

        logger.info(f"SiteExperienceStore initialized: {len(self._experiences)} domains, path={self._storage_path}")

    @staticmethod
    def _resolve_storage_path(path: str | Path | None) -> Path:
        """Resolve storage path (same directory as DomainMetricsManager)"""
        if path is not None:
            return Path(path)

        if os.path.exists("/workspace/"):
            return Path("/workspace/.myrm/site_experience.json")

        return Path.home() / ".myrm" / "site_experience.json"

    def _load(self) -> None:
        """Load site experience from JSON"""
        if not self._storage_path.exists():
            return

        try:
            with open(self._storage_path, encoding="utf-8") as f:
                data = json.load(f)
                self._experiences = {domain: SiteExperience.from_dict(exp_data) for domain, exp_data in data.items()}
            logger.info(f"Loaded {len(self._experiences)} site experiences from {self._storage_path}")
        except Exception:
            logger.error(f"Failed to load site experiences from {self._storage_path}", exc_info=True)
            self._experiences = {}

    def save(self) -> None:
        """Persist to JSON file"""
        if not self._dirty:
            return

        with self._lock:
            snapshot = {domain: exp.to_dict() for domain, exp in self._experiences.items()}
            self._dirty = False

        try:
            from myrm_agent_harness.infra.atomic_write import atomic_write

            atomic_write(self._storage_path, json.dumps(snapshot, indent=2, ensure_ascii=False))
            logger.info(f"Saved {len(snapshot)} site experiences to {self._storage_path}")
        except Exception:
            logger.error(f"Failed to save site experiences to {self._storage_path}", exc_info=True)

    def get(
        self,
        domain: str,
        domain_metrics_manager: DomainMetricsManager | None = None,
    ) -> tuple[SiteExperience | None, bool]:
        """Get domain experience (with cross-validation)

        Args:
            domain: Domain
            domain_metrics_manager: DomainMetricsManager（For cross-validation, optional）

        Returns:
            (experience, possibly_stale)
            - experience: Site experience, None if not found
            - possibly_stale: Whether experience may be stale (low DomainMetrics success rate)
        """
        domain = self._normalize_domain(domain)
        with self._lock:
            exp = self._experiences.get(domain)
            if exp is None:
                return None, False

            exp.last_access = time.time()

        possibly_stale = self._check_staleness(domain, domain_metrics_manager)
        return exp, possibly_stale

    def _check_staleness(
        self,
        domain: str,
        domain_metrics_manager: DomainMetricsManager | None,
    ) -> bool:
        """Cross-validation: check DomainMetrics recent failure count within 24h to determine if experience may be stale

        Uses recent failure count (24h window) instead of global success rate，
        Because global success rate is diluted by historical successes, masking recent consecutive failures。
        """
        if domain_metrics_manager is None:
            return False

        metrics = domain_metrics_manager.get(domain)
        if metrics is None:
            return False

        from ..fetchers.protocols import FetcherType

        recent_failures = sum(metrics.get_recent_failures_count(ft, window_hours=24) for ft in FetcherType)
        return recent_failures >= _STALE_RECENT_FAILURE_THRESHOLD

    def get_prefer_http3(self, domain: str) -> bool:
        """Whether L1 should skip HTTP/2 and use HTTP/3 for this domain."""
        domain = self._normalize_domain(domain)
        with self._lock:
            exp = self._experiences.get(domain)
            return bool(exp and exp.prefer_http3)

    def set_prefer_http3(self, domain: str, *, enabled: bool = True) -> None:
        """Record domain-level HTTP/3 preference after a successful L1 QUIC fetch."""
        domain = self._normalize_domain(domain)
        with self._lock:
            exp = self._experiences.get(domain)
            if exp is None:
                exp = SiteExperience(domain=domain)
                self._experiences[domain] = exp
                if len(self._experiences) > self._max_domains:
                    self._evict_lru()
            exp.prefer_http3 = enabled
            exp.last_access = time.time()
            self._dirty = True

    def save_experience(
        self,
        domain: str,
        *,
        platform_features: list[str] | None = None,
        url_patterns: dict[str, str] | None = None,
        known_traps: list[str] | None = None,
        successful_flows: list[str] | None = None,
    ) -> SiteExperience:
        """Save or update domain experience (incremental merge)

        Args:
            domain: Domain
            platform_features: Platform features (append, deduplicate)
            url_patterns: URL templates (merge, overwrite same key)
            known_traps: Known traps (append, deduplicate)
            successful_flows: Successful flows (append, deduplicate)

        Returns:
            Updated SiteExperience
        """
        domain = self._normalize_domain(domain)
        with self._lock:
            exp = self._experiences.get(domain)
            if exp is None:
                exp = SiteExperience(domain=domain)
                self._experiences[domain] = exp

                if len(self._experiences) > self._max_domains:
                    self._evict_lru()

            if platform_features:
                for feat in platform_features:
                    if feat not in exp.platform_features:
                        exp.platform_features.append(feat)

            if url_patterns:
                exp.url_patterns.update(url_patterns)

            if known_traps:
                for trap in known_traps:
                    if trap not in exp.known_traps:
                        exp.known_traps.append(trap)

            if successful_flows:
                for flow in successful_flows:
                    if flow not in exp.successful_flows:
                        exp.successful_flows.append(flow)

            now = time.time()
            exp.last_verified = time.strftime("%Y-%m-%d", time.localtime(now))
            exp.verification_count += 1
            exp.last_access = now
            self._dirty = True

        return exp

    def delete(self, domain: str) -> bool:
        """Delete domain experience

        Returns:
            Whether existed and was deleted
        """
        domain = self._normalize_domain(domain)
        with self._lock:
            if domain in self._experiences:
                del self._experiences[domain]
                self._dirty = True
                return True
            return False

    def list_domains(self) -> list[str]:
        """List all domains with experience."""
        with self._lock:
            return list(self._experiences.keys())

    def _evict_lru(self) -> None:
        """Evict least recently accessed domain."""
        if not self._experiences:
            return

        lru_domain = min(
            self._experiences.items(),
            key=lambda x: x[1].last_access,
        )[0]
        del self._experiences[lru_domain]
        logger.info(f"Evicted LRU site experience: {lru_domain}")

    def shutdown(self) -> None:
        """Save on close"""
        self.save()

    def get_stats(self) -> dict[str, int | str]:
        """Get statistics"""
        with self._lock:
            return {
                "total_domains": len(self._experiences),
                "storage_path": str(self._storage_path),
                "non_empty_domains": sum(1 for exp in self._experiences.values() if not exp.is_empty()),
            }
