"""A2A AgentCard resolver — discovers third-party agents via URL.

Fetches and parses ``/.well-known/agent-card.json`` from remote servers
with TTL caching, timeout control, and SSRF protection.

[INPUT]
- types::AgentCard, WELL_KNOWN_AGENT_CARD_PATH
- core.security.http.secure_fetch::secure_get (POS: SSRF-protected outbound HTTP)

[OUTPUT]
- A2ACardResolver: Client for discovering remote AgentCards
- resolve(): Fetch and parse AgentCard from URL

[POS]
Framework-level capability for discovering third-party A2A agents.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import httpx

from myrm_agent_harness.core.security.guards.ssrf import SSRFSecurityError
from myrm_agent_harness.toolkits.a2a.types import (
    AgentCard,
    WELL_KNOWN_AGENT_CARD_PATH,
)

logger = logging.getLogger(__name__)


class A2AResolveError(Exception):
    """Failed to resolve an AgentCard from a remote URL."""


class SSRFBlockedError(A2AResolveError):
    """URL blocked by SSRF protection."""


# ---------------------------------------------------------------------------
# Cache entry
# ---------------------------------------------------------------------------


@dataclass
class _CacheEntry:
    card: AgentCard
    expires_at: float


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


@dataclass
class A2ACardResolver:
    """Fetches and caches AgentCards from remote A2A agents.

    Args:
        timeout_seconds: HTTP request timeout.
        cache_ttl_seconds: How long to cache resolved cards (0 = no cache).
    """

    timeout_seconds: float = 30.0
    cache_ttl_seconds: float = 300.0  # 5 分钟默认缓存

    _cache: dict[str, _CacheEntry] = field(
        default_factory=dict, init=False, repr=False
    )

    async def resolve(
        self,
        base_url: str,
        *,
        path: str = WELL_KNOWN_AGENT_CARD_PATH,
        headers: dict[str, str] | None = None,
        skip_ssrf_check: bool = False,
    ) -> AgentCard:
        """Fetch an AgentCard from a remote URL.

        Args:
            base_url: The agent's base URL (e.g. ``https://agent.example.com``).
            path: Override the well-known path.
            headers: Extra HTTP headers (e.g. auth tokens).
            skip_ssrf_check: Skip SSRF validation (for trusted internal calls).

        Returns:
            Parsed AgentCard.

        Raises:
            SSRFBlockedError: If URL fails security validation.
            A2AResolveError: If fetch or parse fails.
        """
        full_url = base_url.rstrip("/") + path
        request_headers = dict(headers or {})

        cache_key = full_url
        cached = self._cache.get(cache_key)
        if cached and cached.expires_at > time.monotonic():
            return cached.card

        try:
            if skip_ssrf_check:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    resp = await client.get(full_url, headers=request_headers)
                    resp.raise_for_status()
                    data = resp.json()
            else:
                from myrm_agent_harness.core.security.http.secure_fetch import secure_get

                resp = await secure_get(
                    full_url,
                    timeout=self.timeout_seconds,
                    headers=request_headers or None,
                )
                resp.raise_for_status()
                data = resp.json()
        except SSRFSecurityError as exc:
            raise SSRFBlockedError(str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            raise A2AResolveError(
                f"AgentCard fetch failed: HTTP {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise A2AResolveError(
                f"AgentCard fetch failed: {exc}"
            ) from exc

        # 解析为强类型 AgentCard
        try:
            card = AgentCard.model_validate(data)
        except Exception as exc:
            raise A2AResolveError(
                f"AgentCard parse failed: {exc}"
            ) from exc

        # 写入缓存
        if self.cache_ttl_seconds > 0:
            self._cache[cache_key] = _CacheEntry(
                card=card,
                expires_at=time.monotonic() + self.cache_ttl_seconds,
            )

        logger.info(
            "Resolved AgentCard from %s: name=%s, skills=%d",
            full_url,
            card.name,
            len(card.skills),
        )
        return card

    def invalidate_cache(self, base_url: str | None = None) -> None:
        """Clear cached AgentCards.

        Args:
            base_url: Clear only this URL's cache. None clears all.
        """
        if base_url is None:
            self._cache.clear()
        else:
            full_url = base_url.rstrip("/") + WELL_KNOWN_AGENT_CARD_PATH
            self._cache.pop(full_url, None)
