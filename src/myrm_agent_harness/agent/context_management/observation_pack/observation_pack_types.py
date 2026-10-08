# [INPUT]: None
# [OUTPUT]: ObservationHandle, ObservationPage, ObservationSendState, ObservationPackConfig, TransformDecision, PackBatchResult
# [POS]: agent/context_management/observation_pack/observation_pack_types.py

"""Domain models and contracts for observation pack handle archival and paged recall.

[INPUT]
- None (Self-contained strongly-typed domain definitions).

[OUTPUT]
- ObservationHandle: Metadata descriptor for an archived large observation.
- ObservationPage: Structured page chunk of an archived observation.
- ObservationSendState: Send count tracker managing full-send sliding windows.
- ObservationPackConfig: Configuration for thresholds, window sizes, and excerpt budgets.
- TransformDecision: Transformation verdict for a single tool observation.
- PackBatchResult: Aggregated result for a batch of transformed messages.

[POS]
Domain contracts powering NVIDIA SoL-Pi inspired ObservationPack degradation and paged recall.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence


@dataclass(frozen=True)
class ObservationHandle:
    """Immutable descriptor of an archived large tool observation."""

    obs_id: str
    sha256_hash: str
    byte_size: int
    line_count: int
    head_excerpt: str
    tail_excerpt: str
    created_at: float


@dataclass(frozen=True)
class ObservationPage:
    """Structured page slice of an archived observation."""

    obs_id: str
    page: int
    page_size: int
    total_pages: int
    total_lines: int
    lines: Sequence[str]
    has_more: bool


@dataclass
class ObservationSendState:
    """Mutable send-count tracker for an observation within a session."""

    obs_id: str
    full_sends_count: int = 0
    is_degraded: bool = False


@dataclass(frozen=True)
class ObservationPackConfig:
    """Configuration governing observation pack thresholds and excerpt budgets."""

    threshold_bytes: int = 10 * 1024  # 10KB threshold
    full_sends: int = 2  # First 2 requests carry 100% full content
    head_bytes: int = 512  # Excerpt head budget
    tail_bytes: int = 512  # Excerpt tail budget
    receipt_prefixes: tuple[str, ...] = (
        "sol_pi_evidence_receipt_v1",
        "myrm_evidence_receipt_v1",
    )
    default_page_size: int = 100


@dataclass(frozen=True)
class TransformDecision:
    """Transformation outcome for an individual observation string."""

    action: str  # "EXEMPT_RECEIPT" | "BELOW_THRESHOLD" | "FULL_SEND_ACTIVE" | "DEGRADED_PLACEHOLDER"
    original_bytes: int
    transformed_bytes: int
    handle_id: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class PackBatchResult:
    """Aggregated outcome of applying observation pack transformations to messages."""

    processed_count: int
    degraded_count: int
    exempt_count: int
    bytes_saved: int
    tokens_saved_estimate: int
    messages: Sequence[Mapping[str, str]]
    decisions: Sequence[TransformDecision] = field(default_factory=list)
