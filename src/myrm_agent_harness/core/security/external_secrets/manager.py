"""Thread-safe external secrets manager with memory caching and single-flight resolution.

[INPUT]
- .protocols::ExternalSecretResolver, ResolverHealth
- json::json
- logging::logging
- os::os
- re::re
- subprocess::subprocess
- threading::threading
- time::time

[OUTPUT]
- ExternalSecretResolutionError: Raised on resolution failure, CLI timeout, or invalid ref
- ExternalSecretsManager: Primary singleton managing resolution, cache, and 401 eviction
- is_external_secret_reference: Helper to check if string matches external vault URI schemes
- get_external_secrets_manager: Global manager accessor

[POS]
Harness core security layer implementation. Resolves external secret references
(1Password, Bitwarden) with in-memory TTL caching, single-flight deduplication,
and non-interactive execution guards so plain secrets never sit on disk.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Final

from myrm_agent_harness.core.security.external_secrets.protocols import (
    ExternalSecretResolver,
    ResolverHealth,
)

logger = logging.getLogger(__name__)

_BW_PREFIXES: Final[tuple[str, ...]] = ("bw://", "bws://")
_OP_PREFIX: Final[str] = "op://"
_DEFAULT_TTL_SECONDS: Final[float] = 600.0  # 10 minutes
_DEFAULT_TIMEOUT_SECONDS: Final[float] = 4.0  # Strict non-interactive timeout
_MAX_CACHE_ENTRIES: Final[int] = 256


class ExternalSecretResolutionError(Exception):
    """Raised when resolving an external secret reference fails or times out."""


@dataclass(slots=True)
class _CacheEntry:
    value: str
    expires_at: float


class ExternalSecretsManager(ExternalSecretResolver):
    """Manager for external secret references with memory caching and deduplication."""

    def __init__(self, default_ttl_seconds: float = _DEFAULT_TTL_SECONDS) -> None:
        self._default_ttl: float = default_ttl_seconds
        self._cache: dict[str, _CacheEntry] = {}
        self._lock: threading.RLock = threading.RLock()
        self._inflight: dict[str, threading.Event] = {}
        self._inflight_results: dict[str, tuple[str | None, Exception | None]] = {}

    def is_supported(self, reference: str) -> bool:
        """Check whether the given string is a supported external vault URI."""
        return is_external_secret_reference(reference)

    def resolve(self, reference: str, force_refresh: bool = False) -> str:
        """Resolve an external secret reference to plaintext in memory.

        Uses thread-safe single-flight to guarantee that concurrent callers
        requesting the same URI share a single CLI invocation.
        """
        ref = _clean_reference(reference)
        if not self.is_supported(ref):
            raise ExternalSecretResolutionError(
                f"Unsupported external secret URI scheme: {reference!r}. Expected op://, bw://, or bws://"
            )

        now = time.monotonic()
        with self._lock:
            if not force_refresh and ref in self._cache:
                entry = self._cache[ref]
                if now < entry.expires_at:
                    return entry.value
                del self._cache[ref]

            # Single-flight deduplication
            if ref in self._inflight:
                event = self._inflight[ref]
                is_leader = False
            else:
                event = threading.Event()
                self._inflight[ref] = event
                is_leader = True

        if not is_leader:
            event.wait(timeout=_DEFAULT_TIMEOUT_SECONDS + 1.0)
            with self._lock:
                if ref in self._cache:
                    return self._cache[ref].value
                val, err = self._inflight_results.get(ref, (None, None))
                if err is not None:
                    raise err
                if val is not None:
                    return val
                return self._execute_cli_resolution(ref)

        try:
            resolved_value = self._execute_cli_resolution(ref)
            with self._lock:
                # Evict oldest entry if cache limit reached
                if len(self._cache) >= _MAX_CACHE_ENTRIES:
                    oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k].expires_at)
                    self._cache.pop(oldest_key, None)
                self._cache[ref] = _CacheEntry(
                    value=resolved_value,
                    expires_at=time.monotonic() + self._default_ttl,
                )
                self._inflight_results[ref] = (resolved_value, None)
            return resolved_value
        except Exception as exc:
            with self._lock:
                self._inflight_results[ref] = (None, exc)
            raise
        finally:
            with self._lock:
                event.set()
                self._inflight.pop(ref, None)
                self._inflight_results.pop(ref, None)

    def invalidate(self, reference: str) -> None:
        """Evict cached entry for reference to trigger refetch on next call (e.g. on 401)."""
        ref = _clean_reference(reference)
        with self._lock:
            self._cache.pop(ref, None)
            logger.info("Evicted external secret cache for reference: %s", ref)

    def clear_cache(self) -> None:
        """Clear all in-memory secret caches."""
        with self._lock:
            self._cache.clear()

    def probe(self) -> ResolverHealth:
        """Probe reachability of local CLI helpers."""
        # Check op first, then bw/bws
        for cmd, scheme in (("op", "op://"), ("bw", "bw://"), ("bws", "bws://")):
            start = time.perf_counter()
            try:
                proc = subprocess.run(
                    [cmd, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=2.0,
                    check=False,
                )
                latency = (time.perf_counter() - start) * 1000.0
                if proc.returncode == 0:
                    return ResolverHealth(scheme=scheme, available=True, latency_ms=latency)
            except Exception:
                continue
        return ResolverHealth(
            scheme="external",
            available=False,
            error_message="Neither 'op', 'bw', nor 'bws' CLI binary is executable in PATH",
        )

    def _execute_cli_resolution(self, ref: str) -> str:
        """Run external CLI helper in isolated, non-interactive environment."""
        env = _build_noninteractive_env()

        if ref.startswith(_OP_PREFIX):
            cmd = ["op", "read", ref]
        elif ref.startswith("bw://"):
            item_target = ref[len("bw://") :].strip()
            cmd = ["bw", "get", "password", item_target]
        elif ref.startswith("bws://"):
            secret_id = ref[len("bws://") :].strip()
            cmd = ["bws", "secret", "get", secret_id, "--output", "json"]
        else:
            raise ExternalSecretResolutionError(f"Unsupported URI scheme: {ref}")

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=_DEFAULT_TIMEOUT_SECONDS,
                env=env,
                check=False,
            )
            if proc.returncode != 0:
                err_msg = proc.stderr.strip()[:240] or f"Process exited with code {proc.returncode}"
                logger.warning("External secret CLI (%s) failed for %s: %s", cmd[0], ref, err_msg)
                raise ExternalSecretResolutionError(f"Failed to resolve {cmd[0]} secret: {err_msg}")

            output = proc.stdout.strip()
            if ref.startswith("bws://"):
                try:
                    payload = json.loads(output)
                    if isinstance(payload, dict) and "value" in payload:
                        return str(payload["value"]).strip()
                except Exception as exc:
                    raise ExternalSecretResolutionError(f"Failed to parse bws JSON output: {exc}") from exc

            if not output:
                raise ExternalSecretResolutionError(f"External secret CLI returned empty value for {ref}")
            return output

        except subprocess.TimeoutExpired as exc:
            logger.error("External secret CLI (%s) timed out (%.1fs) for %s", cmd[0], _DEFAULT_TIMEOUT_SECONDS, ref)
            raise ExternalSecretResolutionError(
                f"External secret resolution timed out ({_DEFAULT_TIMEOUT_SECONDS:.1f}s) for {ref}"
            ) from exc
        except FileNotFoundError as exc:
            raise ExternalSecretResolutionError(
                f"External secret CLI tool '{cmd[0]}' is not installed or not found in system PATH."
            ) from exc


def _clean_reference(raw: str) -> str:
    cleaned = raw.strip()
    if (cleaned.startswith('"') and cleaned.endswith('"')) or (cleaned.startswith("'") and cleaned.endswith("'")):
        cleaned = cleaned[1:-1].strip()
    return cleaned


def is_external_secret_reference(value: str | None) -> bool:
    """Return True if string is formatted as an external vault URI."""
    if not value or not isinstance(value, str):
        return False
    cleaned = _clean_reference(value)
    return cleaned.startswith(_OP_PREFIX) or cleaned.startswith(_BW_PREFIXES)


def _build_noninteractive_env() -> dict[str, str]:
    """Build isolated child process environment suppressing GUI/TTY prompts."""
    child_env = os.environ.copy()
    child_env["OP_BIOMETRIC_UNLOCK_ENABLED"] = "false"
    child_env["OP_LOAD_DESKTOP_APP_SETTINGS"] = "false"
    child_env["BW_NO_PROMPT"] = "true"
    child_env["CI"] = "1"
    return child_env


_GLOBAL_MANAGER: ExternalSecretsManager | None = None
_GLOBAL_LOCK: threading.Lock = threading.Lock()


def get_external_secrets_manager() -> ExternalSecretsManager:
    """Retrieve the process-wide ExternalSecretsManager singleton."""
    global _GLOBAL_MANAGER
    if _GLOBAL_MANAGER is not None:
        return _GLOBAL_MANAGER
    with _GLOBAL_LOCK:
        if _GLOBAL_MANAGER is None:
            _GLOBAL_MANAGER = ExternalSecretsManager()
        return _GLOBAL_MANAGER
