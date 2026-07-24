"""ComboResolver — unified LLM routing engine for Combo chains.

Given a ``ComboConfig`` and the user's provider credential map, the
resolver selects the best target, acquires a credential from
``CredentialPool``, and returns a ``ResolvedTarget`` ready for
``litellm.acompletion``.

On failure the caller feeds the error back via ``report_failure()``
and calls ``resolve()`` again to slide to the next target.

[INPUT]
- combo.combo_types (POS: ComboConfig, ComboTarget, RoutingStrategy)
- combo.strategies (POS: apply_strategy, StrategyContext)
- llms.core.credential_pool (POS: CredentialPool)

[OUTPUT]
- ResolvedTarget: dataclass ready for litellm call
- ComboResolver: stateful per-session resolver

[POS]
Framework-level routing resolver.  No business logic — consumes generic
provider credential dicts and Combo configs.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from myrm_agent_harness.toolkits.llms.core.credential_pool import CredentialPool

from .combo_types import ComboConfig, ComboTarget, RoutingStrategy
from .strategies import StrategyContext, apply_strategy

logger = logging.getLogger(__name__)

ModelFormatterFn = Callable[[str, str], str]
_DEFAULT_COOLDOWN_S = 60.0


@dataclass
class ResolvedTarget:
    """A fully resolved target ready for ``litellm.acompletion``.

    Attributes:
        litellm_model: LiteLLM-format model string (e.g. ``"openai/gpt-4o"``).
        api_key: Active credential selected from the pool.
        base_url: Optional custom API base URL.
        target: Reference to the original ``ComboTarget``.
    """

    litellm_model: str
    api_key: str
    base_url: str | None
    target: ComboTarget


@dataclass
class _TargetState:
    """Per-target runtime state tracked by the resolver."""

    pool: CredentialPool
    cooldown_until: float = 0.0
    consecutive_failures: int = 0


class ComboResolver:
    """Stateful per-session resolver that walks a Combo chain.

    Lifecycle:
        1. Construct with ``ComboConfig`` + provider credentials.
        2. Call ``resolve()`` to get the next ``ResolvedTarget``.
        3. On success call ``report_success(target)`` to reinforce the
           last-known-good state.
        4. On failure call ``report_failure(target, error_kind)`` to
           cooldown/rotate the failed target and re-call ``resolve()``.

    The resolver is lightweight and re-entrant.  It does **not** make
    LLM calls — that's the caller's responsibility.
    """

    def __init__(
        self,
        combo: ComboConfig,
        provider_credentials: dict[str, list[str]],
        provider_base_urls: dict[str, str | None] | None = None,
        litellm_model_fn: ModelFormatterFn | None = None,
    ) -> None:
        self._combo = combo
        self._ctx = StrategyContext()
        self._provider_base_urls = provider_base_urls or {}
        self._litellm_model_fn = litellm_model_fn or _default_litellm_model
        self._target_states: dict[str, _TargetState] = {}

        # Pre-build credential pools
        for target in combo.enabled_targets:
            key = _target_key(target)
            keys = provider_credentials.get(target.provider_id, [])
            if not keys:
                logger.debug("ComboResolver: no credentials for provider %s", target.provider_id)
                continue
            self._target_states[key] = _TargetState(pool=CredentialPool(keys))

    def resolve(self) -> ResolvedTarget | None:
        """Select the best available target from the Combo chain.

        Returns ``None`` when all targets are exhausted or in cooldown.
        """
        enabled = self._combo.enabled_targets
        if not enabled:
            return None

        ordered = apply_strategy(enabled, self._combo.strategy, self._ctx)
        now = time.monotonic()

        for target in ordered:
            key = _target_key(target)
            state = self._target_states.get(key)
            if state is None:
                continue
            if state.cooldown_until > now:
                continue

            api_key = state.pool.acquire()
            base_url = self._provider_base_urls.get(target.provider_id)
            litellm_model = self._litellm_model_fn(target.provider_id, target.model)

            self._ctx.request_counts[key] = self._ctx.request_counts.get(key, 0) + 1

            return ResolvedTarget(
                litellm_model=litellm_model,
                api_key=api_key,
                base_url=base_url,
                target=target,
            )

        # All targets exhausted — try the one with earliest recovery
        earliest_key: str | None = None
        earliest_time = float("inf")
        for key, state in self._target_states.items():
            if state.cooldown_until < earliest_time:
                earliest_time = state.cooldown_until
                earliest_key = key

        if earliest_key is not None:
            state = self._target_states[earliest_key]
            target = next(
                (t for t in enabled if _target_key(t) == earliest_key),
                None,
            )
            if target is not None:
                api_key = state.pool.acquire()
                base_url = self._provider_base_urls.get(target.provider_id)
                litellm_model = self._litellm_model_fn(target.provider_id, target.model)
                return ResolvedTarget(
                    litellm_model=litellm_model,
                    api_key=api_key,
                    base_url=base_url,
                    target=target,
                )

        return None

    def report_success(self, resolved: ResolvedTarget) -> None:
        """Record a successful call — reinforce LKGP and reset cooldown."""
        key = _target_key(resolved.target)
        state = self._target_states.get(key)
        if state is not None:
            state.consecutive_failures = 0
            state.cooldown_until = 0.0
            state.pool.report_success(resolved.api_key)

        self._ctx.lkgp_target_key = key
        self._ctx.context_relay_target_key = key

    def report_failure(
        self,
        resolved: ResolvedTarget,
        error_kind: str = "rate_limit",
        cooldown_hint_s: float | None = None,
    ) -> None:
        """Record a failed call — cooldown the target and its credential."""
        key = _target_key(resolved.target)
        state = self._target_states.get(key)
        if state is None:
            return

        state.pool.report_error(resolved.api_key, error_kind, cooldown_hint_s)

        state.consecutive_failures += 1
        backoff = min(
            _DEFAULT_COOLDOWN_S * (2.0 ** min(state.consecutive_failures - 1, 5)),
            600.0,
        )
        state.cooldown_until = time.monotonic() + backoff

        logger.info(
            "ComboResolver: target %s failed (%s), cooldown %.0fs (consecutive=%d)",
            key,
            error_kind,
            backoff,
            state.consecutive_failures,
        )

    @property
    def max_retries(self) -> int:
        return self._combo.max_retries

    @property
    def retry_on_status(self) -> frozenset[int]:
        return self._combo.retry_on_status


def _target_key(t: ComboTarget) -> str:
    return f"{t.provider_id}/{t.model}"


def _default_litellm_model(provider_id: str, model: str) -> str:
    return f"{provider_id}/{model}"
