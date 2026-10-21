"""Loopback network proxy environment guard and static bypass injector.

Hardens execution environments against accidental local loopback traffic interception
by transparently augmenting NO_PROXY and sanitizing local subprocess environments.

[OUTPUT]
- ProxyEnvironmentGuard: Static environment guard and loopback identifier.

[INPUT]
- __future__
- os
- collections
- urllib

[OUTPUT]
- ProxyEnvironmentGuard

[POS]
Loopback network proxy environment guard and static bypass injector.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from urllib.parse import urlparse

from myrm_agent_harness.core.network.loopback_types import (
    ProxyEnvironmentSnapshot,
)

_DEFAULT_LOOPBACK_TOKENS: tuple[str, ...] = (
    "127.0.0.1",
    "localhost",
    "::1",
    "127.0.0.0/8",
    "*.local",
)


class ProxyEnvironmentGuard:
    """Provides environment sanitation and loopback bypass injection."""

    @staticmethod
    def is_loopback_target(target: str) -> bool:
        """Evaluate if target host or URL refers to local machine loopback.

        Accepts hostnames, IPs, or full URLs (e.g., 'http://127.0.0.1:8317').
        """
        candidate = target.strip()
        if "://" in candidate:
            parsed = urlparse(candidate)
            host = parsed.hostname or ""
        elif candidate.startswith("[") and "]" in candidate:
            host = candidate[1 : candidate.index("]")]
        elif candidate in {"::1", "::"}:
            host = candidate
        elif ":" in candidate and candidate.count(":") == 1:
            host = candidate.split(":")[0].strip()
        else:
            host = candidate

        host_lower = host.lower()
        if host_lower in {"127.0.0.1", "localhost", "::1"}:
            return True
        return host_lower.startswith("127.")

    @staticmethod
    def capture_snapshot(
        env: Mapping[str, str] | None = None,
    ) -> ProxyEnvironmentSnapshot:
        """Capture standard and uppercase proxy environment variables."""
        source = env if env is not None else os.environ

        def _get_val(key: str) -> str | None:
            return source.get(key) or source.get(key.upper())

        return ProxyEnvironmentSnapshot(
            http_proxy=_get_val("http_proxy"),
            https_proxy=_get_val("https_proxy"),
            all_proxy=_get_val("all_proxy"),
            no_proxy=_get_val("no_proxy"),
        )

    @staticmethod
    def merge_no_proxy(
        existing_no_proxy: str | None,
        additional_tokens: tuple[str, ...] = _DEFAULT_LOOPBACK_TOKENS,
    ) -> str:
        """Merge additional loopback bypass tokens into an existing NO_PROXY string."""
        current_tokens = [
            t.strip() for t in (existing_no_proxy or "").split(",") if t.strip()
        ]
        seen_lower = {t.lower() for t in current_tokens}

        for token in additional_tokens:
            if token.lower() not in seen_lower:
                current_tokens.append(token)
                seen_lower.add(token.lower())

        return ",".join(current_tokens)

    @classmethod
    def enforce_loopback_bypass(
        cls,
        target_env: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Inject complete loopback bypass definitions into target_env or os.environ."""
        mutate_process = target_env is None
        env_dict = target_env if target_env is not None else dict(os.environ)

        existing = env_dict.get("no_proxy") or env_dict.get("NO_PROXY")
        merged = cls.merge_no_proxy(existing)

        env_dict["no_proxy"] = merged
        env_dict["NO_PROXY"] = merged

        if mutate_process:
            os.environ["no_proxy"] = merged
            os.environ["NO_PROXY"] = merged

        return env_dict

    @classmethod
    def sanitize_client_env(
        cls,
        target_endpoint: str,
        base_env: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        """Strip proxy variables when connecting to loopback targets to prevent routing deadlocks."""
        source = dict(base_env if base_env is not None else os.environ)

        if cls.is_loopback_target(target_endpoint):
            for proxy_key in (
                "http_proxy",
                "HTTP_PROXY",
                "https_proxy",
                "HTTPS_PROXY",
                "all_proxy",
                "ALL_PROXY",
            ):
                source.pop(proxy_key, None)

        # Ensure NO_PROXY is present in any case
        return cls.enforce_loopback_bypass(source)
