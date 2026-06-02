"""Consensus (MoA) data types.

[OUTPUT]
- ConsensusConfig: immutable configuration for a consensus run
- ReferenceResponse: single reference model's response
- ConsensusResult: aggregated result of a consensus run

[POS]
Framework-level data types for multi-model consensus inference.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ConsensusConfig:
    """Immutable configuration for a consensus (MoA) run.

    The reference and aggregator models themselves are supplied as
    ``BaseChatModel`` instances to :class:`ConsensusEngine`; this object only
    carries the execution parameters applied to those calls.

    Attributes:
        reference_temperature: sampling temperature applied to reference model
            calls (higher = more diverse answers, the MoA diversity lever).
        aggregator_temperature: sampling temperature applied to the aggregator
            call (lower = more focused synthesis).
        min_successful: minimum number of reference responses required
            before aggregation proceeds.  Setting this to 1 allows the
            pipeline to degrade gracefully when some models are unavailable.
        timeout_per_model: per-model timeout in seconds.
        timeout_total: global timeout in seconds for the entire run.
        max_retries_per_model: retry attempts per reference model.
    """

    reference_temperature: float = 0.6
    aggregator_temperature: float = 0.4
    min_successful: int = 1
    timeout_per_model: float = 120.0
    timeout_total: float = 300.0
    max_retries_per_model: int = 2


@dataclass(slots=True)
class ReferenceResponse:
    """A single reference model's response."""

    model: str
    content: str
    elapsed_seconds: float
    success: bool
    error: str | None = None


@dataclass(slots=True)
class ConsensusResult:
    """Aggregated result of a consensus run."""

    final_answer: str
    reference_responses: list[ReferenceResponse] = field(default_factory=list)
    aggregator_model: str = ""
    elapsed_seconds: float = 0.0
    success: bool = True
    error: str | None = None
