"""Output-budget scaling for streaming truncation recovery.

[INPUT]
- toolkits.llms.ephemeral_output_tokens (POS: ephemeral max-output-tokens ContextVar and its cap)
- toolkits.llms.utils.model_utils::clamp_budget_to_model_ceiling (POS: keeps a boosted output budget within the model's known ceiling)
- toolkits.llms.core.thinking_headroom::thinking_output_floor (POS: headroom floor of a thinking model)
- agent.streaming.stream_executor::StreamContext (POS: active LLM of the running turn)

[OUTPUT]
- StreamOutputBudgetMixin: derives the base output budget of the active LLM and sets the one-shot
  larger budget a recovery retry runs with.

[POS]
Budget half of the truncation recovery layer: the continuation and tool-call retries in
`stream_recovery_truncation` decide *when* to retry, this mixin decides *how much* room the retry gets.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.llms.ephemeral_output_tokens import (
    MAX_EPHEMERAL_OUTPUT_TOKENS,
    set_ephemeral_max_output_tokens,
)
from myrm_agent_harness.toolkits.llms.utils.model_utils import clamp_budget_to_model_ceiling
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from myrm_agent_harness.agent.streaming.stream_executor import StreamContext

logger = get_agent_logger(__name__)


class StreamOutputBudgetMixin:
    _ctx: StreamContext

    def _boost_output_tokens(self, retries: int) -> None:
        """Set ephemeral output token override with progressive scaling.

        retries=0 → 2x base, retries=1 → 3x base, retries>=2 → 4x base.
        Capped at MAX_EPHEMERAL_OUTPUT_TOKENS (65536) and at the model's known output ceiling,
        so a retry cannot turn a truncated answer into a hard provider error. A base already at
        a cap is left as configured; a ceiling below the base is a stale table entry and is ignored.

        When no output budget is configured, the provider default applies and its size
        is unknown. For a known thinking model the headroom floor is a safe base (it is
        the same value applied at creation time), so the retry gets real room. For
        anything else the base is unknown, so the boost stays a no-op rather than guessing.
        """
        base = self._get_configured_max_tokens()
        if base is None:
            base = self._default_output_tokens()
        if base is None:
            logger.warning(" Output token boost skipped: no configured max_tokens and model ceiling unknown")
            return

        multiplier = min(retries + 2, 4)
        boosted = clamp_budget_to_model_ceiling(
            self._model_name(),
            min(base * multiplier, MAX_EPHEMERAL_OUTPUT_TOKENS),
            accepted=base,
        )
        if boosted <= base:
            logger.warning(" Output token boost skipped: configured budget %d already reaches the cap or ceiling", base)
            return
        set_ephemeral_max_output_tokens(boosted)
        logger.info(
            " Output token boost: %d → %d (×%d, cap %d)",
            base,
            boosted,
            multiplier,
            MAX_EPHEMERAL_OUTPUT_TOKENS,
        )

    def _model_name(self) -> str:
        """Model identifier of the active LLM, or an empty string when unavailable."""
        llm = self._ctx.llm
        model = getattr(llm, "model_name", None) or getattr(llm, "model", None)
        return model if isinstance(model, str) else ""

    def _default_output_tokens(self) -> int | None:
        """Resolve a safe base output budget when none is configured.

        Only thinking models qualify: their headroom floor is a value already applied
        at creation time, so the boost starts from a budget the provider serves.
        Returns None for unknown models, keeping the boost a safe no-op.
        """
        from myrm_agent_harness.toolkits.llms.core.thinking_headroom import (
            thinking_output_floor,
        )

        model = self._model_name()
        if not model:
            return None
        llm_kwargs = getattr(self._ctx.llm, "model_kwargs", None)
        return thinking_output_floor(model, llm_kwargs if isinstance(llm_kwargs, dict) else None)

    def _get_configured_max_tokens(self) -> int | None:
        """Read the configured max_tokens from the LLM instance.

        Checks ``llm.max_tokens`` first (direct Pydantic field), then falls
        back to ``llm.model_kwargs["max_tokens"]`` which is where the value
        lands when users set it via the frontend ModelKwargsEditor.
        """
        ctx = self._ctx
        llm = ctx.llm
        if llm is None:
            return None
        max_tokens: int | None = getattr(llm, "max_tokens", None)
        if not isinstance(max_tokens, int) or max_tokens <= 0:
            model_kwargs = getattr(llm, "model_kwargs", None) or {}
            raw = model_kwargs.get("max_tokens")
            max_tokens = raw if isinstance(raw, int) and raw > 0 else None
        return max_tokens


__all__ = ["StreamOutputBudgetMixin"]
