"""Cost computation engine with provenance tracking.

[INPUT]
- litellm (POS: LLM unified interface, lazy import for cost calculation)

[OUTPUT]
- CostStatus: Cost provenance enum (actual / estimated / unknown)
- CostResult: Computed cost with status
- compute_cost(): Calculate cost from response object via litellm
- compute_cost_by_tokens(): Calculate cost from token counts via litellm (for streaming)

[POS]
Thin wrapper over litellm.completion_cost() that adds CostStatus provenance.
Consumers (TokenTracker, UsageLedger) know whether a cost figure is real,
estimated, or unavailable — enabling frontend display of confidence level.
"""

import logging
from dataclasses import dataclass
from enum import StrEnum

logger = logging.getLogger(__name__)


class CostStatus(StrEnum):
    """Cost provenance — how the cost figure was obtained."""

    ACTUAL = "actual"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class CostResult:
    """Cost computation result with provenance."""

    usd: float = 0.0
    status: CostStatus = CostStatus.UNKNOWN

    @property
    def is_known(self) -> bool:
        return self.status != CostStatus.UNKNOWN


def compute_cost(
    response_obj: object,
    model: str | None,
) -> CostResult:
    """Compute cost via litellm.completion_cost(), returning CostResult with provenance.

    Returns CostResult(usd=0.0, status=UNKNOWN) on any failure.
    """
    if not model:
        return CostResult()

    try:
        import litellm

        cost = float(litellm.completion_cost(completion_response=response_obj, model=model))
        if cost > 0:
            return CostResult(usd=cost, status=CostStatus.ACTUAL)
        return CostResult(usd=0.0, status=CostStatus.UNKNOWN)
    except Exception:
        logger.debug("Cost computation failed for model=%s", model, exc_info=True)
        return CostResult()


def compute_cost_by_tokens(
    model: str | None,
    prompt_tokens: int,
    completion_tokens: int,
) -> CostResult:
    """Compute cost from token counts via litellm.completion_cost().

    Used for streaming mode where no complete response object is available.
    Returns CostResult(usd=0.0, status=UNKNOWN) on any failure.
    """
    if not model or (prompt_tokens <= 0 and completion_tokens <= 0):
        return CostResult()

    try:
        import litellm

        cost = float(
            litellm.completion_cost(
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
        )
        if cost > 0:
            return CostResult(usd=cost, status=CostStatus.ACTUAL)
        return CostResult(usd=0.0, status=CostStatus.UNKNOWN)
    except Exception:
        logger.debug("Token-based cost computation failed for model=%s", model, exc_info=True)
        return CostResult()
