"""A request's output-token budget: truncation-boost override and provider-stated limits.

[INPUT]
- errors.output_limit::parse_output_limit (POS: output limit a provider printed in a rejection)
- errors.classifier::normalize_provider_error (POS: HTTP status of the rejection)
- toolkits.llms.ephemeral_output_tokens (POS: one-shot larger budget set by truncation recovery)

[OUTPUT]
- recover_output_cap(): lower a rejected request's ``max_tokens`` to what the provider says it accepts
- apply_learned_output_cap(): clamp a request to a model ceiling this endpoint already rejected once
- ChatLiteLLMOutputCapMixin: resolves a request's ``max_tokens`` and recovers from a rejected one

[POS]
Shared by the sync/async generation and streaming loops of ChatLiteLLM. Only ``max_tokens`` ever
changes between attempts: messages, tools and thinking/reasoning parameters stay byte-identical, so
the provider's prompt-prefix cache still hits on the retry. Anything the provider did not state
leaves the request untouched and the original error propagates.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.llms.ephemeral_output_tokens import (
    get_ephemeral_max_output_tokens,
    reset_ephemeral_max_output_tokens,
)
from myrm_agent_harness.toolkits.llms.errors.classifier import normalize_provider_error
from myrm_agent_harness.toolkits.llms.errors.output_limit import parse_output_limit

logger = logging.getLogger(__name__)

# A recovered budget below this cannot hold a useful answer; failing fast lets the caller compress or fail over instead.
_MIN_RECOVERED_TOKENS = 500
# Headroom under a window remainder, which providers compute from their own (slightly different) token count.
_WINDOW_MARGIN_TOKENS = 64
# HTTP statuses providers use for a rejected request body; other statuses never carry an output limit.
_REJECTION_STATUSES = frozenset({400, 413, 422})

# (model, base_url) -> (ceiling, expiry): endpoints whose model ceiling was rejected once, so later requests
# in this process skip the failed call. Bounded and expiring, because a provider may raise its ceiling later.
_LEARNED_CEILINGS: dict[tuple[str, str], tuple[int, float]] = {}
_LEARNED_CEILINGS_MAX = 256
_LEARNED_CEILING_TTL_S = 3600.0


def _endpoint_key(model: str, base_url: str) -> tuple[str, str]:
    return model.strip().lower(), base_url.strip().lower()


def _remember_ceiling(model: str, base_url: str, ceiling: int) -> None:
    key = _endpoint_key(model, base_url)
    if key == ("", ""):
        return
    if key not in _LEARNED_CEILINGS and len(_LEARNED_CEILINGS) >= _LEARNED_CEILINGS_MAX:
        _LEARNED_CEILINGS.pop(next(iter(_LEARNED_CEILINGS)), None)
    _LEARNED_CEILINGS[key] = (ceiling, time.monotonic() + _LEARNED_CEILING_TTL_S)


def _thinking_budget(params: dict[str, object]) -> int | None:
    """Return the ``thinking.budget_tokens`` the request carries (top level or ``extra_body``), if any."""
    extra_body = params.get("extra_body")
    for holder in (params, extra_body if isinstance(extra_body, dict) else {}):
        thinking = holder.get("thinking")
        if isinstance(thinking, dict) and isinstance(budget := thinking.get("budget_tokens"), int):
            return budget
    return None


def apply_learned_output_cap(params: dict[str, object], *, model: str, base_url: str) -> None:
    """Lower ``max_tokens`` to a model ceiling this endpoint already rejected; never raises it."""
    key = _endpoint_key(model, base_url)
    learned = _LEARNED_CEILINGS.get(key)
    if learned is None:
        return
    ceiling, expires_at = learned
    if time.monotonic() >= expires_at:
        _LEARNED_CEILINGS.pop(key, None)
        return
    requested = params.get("max_tokens")
    if isinstance(requested, int) and requested > ceiling:
        params["max_tokens"] = ceiling
        logger.info(" max_tokens %d clamped to the learned ceiling %d of %s", requested, ceiling, model)


def recover_output_cap(exc: Exception, params: dict[str, object], *, model: str, base_url: str) -> bool:
    """Lower ``params["max_tokens"]`` to the limit a rejected request's error states; True when the caller should retry.

    A model ceiling is adopted as stated and remembered for the endpoint; a window remainder is
    adopted minus a safety margin and applies to this request only. The retry is refused when the
    adopted value would not lower the budget, is too small to answer with, or would not leave room
    for the request's own thinking budget.
    """
    status = normalize_provider_error(exc).status_code
    if status is not None and status not in _REJECTION_STATUSES:
        return False
    limit = parse_output_limit(exc)
    if limit is None:
        return False

    adopted = limit.tokens if limit.model_cap else limit.tokens - _WINDOW_MARGIN_TOKENS
    requested = params.get("max_tokens")
    if adopted < _MIN_RECOVERED_TOKENS or (isinstance(requested, int) and adopted >= requested):
        return False
    thinking_budget = _thinking_budget(params)
    if thinking_budget is not None and adopted <= thinking_budget:
        return False

    params["max_tokens"] = adopted
    if limit.model_cap:
        _remember_ceiling(model, base_url, adopted)
    logger.warning(
        " Provider rejected max_tokens=%s (%s of %d); retrying with max_tokens=%d",
        requested,
        "model ceiling" if limit.model_cap else "window remainder",
        limit.tokens,
        adopted,
    )
    return True


class ChatLiteLLMOutputCapMixin:
    """Resolves a request's ``max_tokens`` and recovers from a provider rejection of it."""

    if TYPE_CHECKING:
        api_base: str | None
        model: str
        model_name: str | None

    def _endpoint_identity(self) -> tuple[str, str]:
        return self.model_name or self.model, str(self.api_base or "")

    @staticmethod
    def _apply_ephemeral_output_override(params: dict[str, object]) -> None:
        """Apply and consume the ephemeral max-output-tokens override if set.

        The truncation recovery layer sets this ContextVar to progressively
        boost the output budget during text continuation or tool-call retry.
        The override is consumed (reset to None) after a single read so that
        subsequent normal calls use the configured default.
        """
        override = get_ephemeral_max_output_tokens()
        if override is not None:
            params["max_tokens"] = override
            reset_ephemeral_max_output_tokens()
            logger.info(" Ephemeral max_tokens override applied: %d", override)

    def _apply_output_budget(self, params: dict[str, object]) -> None:
        """Resolve ``max_tokens`` for one request: the boost override first, then the learned model ceiling.

        The ceiling is applied last because a boosted budget must still fit what this endpoint accepts.
        """
        self._apply_ephemeral_output_override(params)
        model, base_url = self._endpoint_identity()
        apply_learned_output_cap(params, model=model, base_url=base_url)

    def _recover_output_cap(self, exc: Exception, params: dict[str, object]) -> bool:
        model, base_url = self._endpoint_identity()
        return recover_output_cap(exc, params, model=model, base_url=base_url)
