"""Provider rate-limit window extraction metrics.

[INPUT]
- observability.metrics::create_counter (POS: Harness-layer generic metrics utilities)

[OUTPUT]
- record_window_outcome: count one rate-limit-class error by the signal its hint was read from

[POS]
Drift alarm for the provider-window extractor. A growing share of the ``none`` label
among rate-limit-class errors means a provider changed its error shape and the
extractor no longer sees the retry boundary. Not a delivery gate.
"""

from __future__ import annotations

from myrm_agent_harness.observability.metrics import create_counter

provider_window_outcome_total = create_counter(
    "provider_window_outcome_total",
    "Rate-limit-class LLM errors by the signal their retry boundary was read from (none = no boundary found)",
    ("source",),
)


def record_window_outcome(source: str) -> None:
    """Record one rate-limit-class error; *source* is a ``WindowSource`` value or ``"none"``."""
    if provider_window_outcome_total is not None:
        provider_window_outcome_total.labels(source=source).inc()
