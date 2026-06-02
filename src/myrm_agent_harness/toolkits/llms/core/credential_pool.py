"""Credential pool for API key rotation within the same model/provider.

Manages multiple API keys with selectable dispatch strategies
(round_robin, fill_first, random, least_used) and error-aware cooldown.
When one key hits a rate limit, auth failure, or billing error, the
pool applies an appropriate cooldown and rotates to the next available key.
Cooldown durations are always maximized to prevent premature key reuse.

[INPUT]

[OUTPUT]
- CredentialPoolStrategy: strategy enum for key dispatch
- normalize_api_keys: order-preserving API key normalization utility
- CredentialPool: key pool with selectable dispatch strategies, error-aware cooldown, and stats

[POS]
Framework-level credential scheduling and rotation. Enables transparent
multi-key dispatch for high-throughput scenarios (multi-pane, concurrent
agent execution).
"""

from __future__ import annotations

import logging
import os
import random
import time
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

logger = logging.getLogger(__name__)

_DEFAULT_COOLDOWN_S = 60.0
_AUTH_COOLDOWN_S = 86_400.0  # 24h — auth/billing failures are effectively permanent
_MAX_COOLDOWN_S = 86_400.0  # 24h cap for exponential backoff
_BACKOFF_FACTOR = 2.0  # double cooldown on consecutive rate limits
_JITTER_RATIO = 0.15  # ±15% random jitter to prevent thundering herd
_STRATEGY_ENV_VAR = "MYRM_LLM_CREDENTIAL_POOL_STRATEGY"


def _normalize_identifier(s: str) -> str:
    """Normalize strategy or error kind identifiers for consistent matching."""
    return s.strip().replace("-", "_").lower()


def normalize_api_keys(keys: Sequence[str]) -> list[str]:
    """Deduplicate API keys while preserving first-seen order."""
    seen: set[str] = set()
    unique_keys: list[str] = []
    for key in keys:
        if key not in seen:
            seen.add(key)
            unique_keys.append(key)
    return unique_keys


class CredentialPoolStrategy(StrEnum):
    """Dispatch strategy used to select the next available credential."""

    ROUND_ROBIN = "round_robin"
    FILL_FIRST = "fill_first"
    LEAST_USED = "least_used"
    RANDOM = "random"

    @classmethod
    def resolve(cls, strategy: CredentialPoolStrategy | str | None) -> CredentialPoolStrategy:
        """Resolve a strategy from an explicit value or the environment."""
        candidate: CredentialPoolStrategy | str | None = strategy
        if candidate is None:
            env_value = os.getenv(_STRATEGY_ENV_VAR)
            if env_value is None or not env_value.strip():
                return cls.ROUND_ROBIN
            candidate = env_value

        if isinstance(candidate, cls):
            return candidate

        normalized = _normalize_identifier(candidate)
        if not normalized:
            return cls.ROUND_ROBIN

        try:
            return cls(normalized)
        except ValueError as exc:
            valid_values = ", ".join(member.value for member in cls)
            raise ValueError(
                f"Unsupported credential pool strategy '{candidate}'. Valid values: {valid_values}"
            ) from exc


@dataclass
class _KeySlot:
    """Internal state for a single API key."""

    key: str
    cooldown_until: float = 0.0
    call_count: int = 0
    rate_limit_count: int = 0
    error_count: int = 0
    consecutive_rate_limit_count: int = 0


class CredentialPool:
    """API key pool with strategy-aware dispatch and error-aware cooldown.

    When a key triggers an error, it enters an appropriate cooldown:
    - Rate limit: exponential backoff with jitter (base * 2^n, ±15 %)
      or server-supplied ``Retry-After`` value when available
    - Auth / billing failure: 24 h (effectively permanent)

    On successful calls, ``report_success()`` resets the consecutive
    error counter so the next rate-limit starts from base cooldown.

    Subsequent ``acquire()`` calls skip cooled-down keys.

    Example::

        pool = CredentialPool(["sk-key1", "sk-key2", "sk-key3"])
        key = pool.acquire()       # "sk-key1"
        pool.report_error(key, "rate_limit")  # key1 cooldown ~60s
        key = pool.acquire()       # "sk-key2" (key1 skipped)
        # ... key2 succeeds ...
        pool.report_success(key2)  # reset consecutive counter
    """

    __slots__ = ("_cooldown_s", "_next_idx", "_slots", "_strategy")

    def __init__(
        self,
        keys: list[str],
        cooldown_s: float = _DEFAULT_COOLDOWN_S,
        *,
        strategy: CredentialPoolStrategy | str | None = None,
    ) -> None:
        unique_keys = normalize_api_keys(keys)
        if not unique_keys:
            raise ValueError("CredentialPool requires at least one key")
        self._slots = [_KeySlot(key=k) for k in unique_keys]
        self._cooldown_s = max(cooldown_s, 1.0)
        self._next_idx = 0
        self._strategy = (
            CredentialPoolStrategy.ROUND_ROBIN
            if len(self._slots) <= 1
            else CredentialPoolStrategy.resolve(strategy)
        )

    @property
    def size(self) -> int:
        return len(self._slots)

    @property
    def is_single_key(self) -> bool:
        return len(self._slots) == 1

    @property
    def strategy(self) -> CredentialPoolStrategy:
        return self._strategy

    def _available_slots(self, now: float) -> list[_KeySlot]:
        return [slot for slot in self._slots if slot.cooldown_until <= now]

    def _earliest_recovery_slot(self) -> _KeySlot:
        return min(self._slots, key=lambda slot: slot.cooldown_until)

    def _select_round_robin_slot(self, now: float) -> _KeySlot:
        n = len(self._slots)
        for _ in range(n):
            slot = self._slots[self._next_idx]
            self._next_idx = (self._next_idx + 1) % n
            if slot.cooldown_until <= now:
                return slot
        return self._earliest_recovery_slot()

    def _select_slot(self, now: float) -> _KeySlot:
        if self._strategy is CredentialPoolStrategy.ROUND_ROBIN:
            return self._select_round_robin_slot(now)

        available_slots = self._available_slots(now)
        if available_slots:
            if self._strategy is CredentialPoolStrategy.FILL_FIRST:
                return available_slots[0]
            if self._strategy is CredentialPoolStrategy.LEAST_USED:
                return min(available_slots, key=lambda slot: slot.call_count)
            return random.choice(available_slots)

        return self._earliest_recovery_slot()

    def acquire(self) -> str:
        """Get the next available key using the configured strategy.

        If all keys are in cooldown, returns the one with the earliest recovery.
        """
        slot = self._select_slot(time.monotonic())
        slot.call_count += 1
        return slot.key

    def report_error(
        self,
        key: str,
        error_kind: str,
        cooldown_hint_s: float | None = None,
    ) -> None:
        """Report an error for *key* and apply an appropriate cooldown.

        Cooldown strategy:
        - Auth / billing: fixed 24 h (effectively permanent for a session).
        - Rate limit with Retry-After hint: use the server-specified value.
        - Rate limit without hint: exponential backoff (base * 2^consecutive)
          with ±15 % jitter, capped at 24 h.  This prevents thundering herd
          when multiple keys recover simultaneously.
        - Other transient errors: fixed default cooldown.

        Args:
            key: The API key that encountered the error.
            error_kind: One of ``"rate_limit"``, ``"auth"``, ``"billing"``,
                or any other string (treated as transient).
            cooldown_hint_s: Optional provider-supplied cooldown (e.g. from
                ``Retry-After`` header). Used only for ``rate_limit``; ignored
                for auth/billing (those use a fixed 24 h cooldown).
        """
        now = time.monotonic()
        normalized_error_kind = _normalize_identifier(error_kind)

        for slot in self._slots:
            if slot.key != key:
                continue

            if normalized_error_kind in ("auth", "billing"):
                cooldown = _AUTH_COOLDOWN_S
                slot.consecutive_rate_limit_count = 0
            elif normalized_error_kind == "rate_limit":
                slot.rate_limit_count += 1
                slot.consecutive_rate_limit_count += 1
                if cooldown_hint_s is not None and cooldown_hint_s > 0:
                    cooldown = cooldown_hint_s
                else:
                    # Exponential backoff: base * 2^(n-1), capped
                    base = self._cooldown_s
                    backoff = min(
                        base * (_BACKOFF_FACTOR ** (slot.consecutive_rate_limit_count - 1)),
                        _MAX_COOLDOWN_S,
                    )
                    # Add ±jitter to stagger recovery across keys
                    jitter = backoff * _JITTER_RATIO * (2.0 * random.random() - 1.0)
                    cooldown = max(backoff + jitter, 1.0)
            else:
                cooldown = self._cooldown_s
                slot.consecutive_rate_limit_count = 0

            slot.cooldown_until = max(slot.cooldown_until, now + cooldown)
            slot.error_count += 1
            logger.warning(
                "CredentialPool: key ...%s %s, cooldown %.0fs (consecutive_rl=%d)",
                key[-4:],
                normalized_error_kind,
                slot.cooldown_until - now,
                slot.consecutive_rate_limit_count,
            )
            break

    def report_success(self, key: str) -> None:
        """Report a successful call for *key*, resetting consecutive error tracking.

        Called after a successful LLM invocation. Resets the consecutive
        rate-limit counter so the next rate-limit starts with base cooldown
        instead of an exponentially grown one.
        """
        for slot in self._slots:
            if slot.key == key:
                slot.consecutive_rate_limit_count = 0
                break

    def available_count(self) -> int:
        """Number of keys not currently in cooldown."""
        return len(self._available_slots(time.monotonic()))

    def stats(self) -> dict[str, object]:
        """Pool statistics for observability."""
        now = time.monotonic()
        available_slots = self._available_slots(now)
        return {
            "strategy": self._strategy.value,
            "total_keys": len(self._slots),
            "available_keys": len(available_slots),
            "total_calls": sum(s.call_count for s in self._slots),
            "total_rate_limits": sum(s.rate_limit_count for s in self._slots),
            "max_consecutive_rate_limits": max(
                (s.consecutive_rate_limit_count for s in self._slots), default=0
            ),
            "total_errors": sum(s.error_count for s in self._slots),
            "keys": [
                {
                    "suffix": s.key[-4:],
                    "calls": s.call_count,
                    "rate_limits": s.rate_limit_count,
                    "consecutive_rate_limits": s.consecutive_rate_limit_count,
                    "errors": s.error_count,
                    "in_cooldown": s.cooldown_until > now,
                    "cooldown_remaining_s": max(0.0, s.cooldown_until - now),
                }
                for s in self._slots
            ],
        }
