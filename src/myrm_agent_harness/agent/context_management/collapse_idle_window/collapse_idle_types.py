"""Domain contracts and data types for collapse-idle-before-cut stream windowing.

[INPUT]
- None (Self-contained strongly-typed contracts).

[OUTPUT]
- StepType: Discriminator of stream steps (idle, error, action, observation, final, reasoning).
- StreamStepItem: Canonical immutable model representing an event or execution step in a stream.
- CollapseWindowConfig: Parameter configuration controlling window sizes and pruning policies.
- CollapseWindowReceipt: Audit receipt recording step reduction counts and preservation metrics.

[POS]
Data structures and domain types for stream idle collapse and window cutting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import time
from typing import Mapping


class StepType(str, Enum):
    """Category classification of stream events."""

    IDLE = "idle"
    ERROR = "error"
    ACTION = "action"
    OBSERVATION = "observation"
    FINAL = "final"
    REASONING = "reasoning"


@dataclass(frozen=True)
class StreamStepItem:
    """Immutable representation of a step or message in the session execution stream."""

    step_id: str
    run_id: str
    step_type: StepType
    content: str
    timestamp: float
    return_code: int | None = None
    collapsed_count: int = 1
    duration_seconds: float = 0.0
    first_timestamp: float | None = None
    last_timestamp: float | None = None
    metadata: Mapping[str, str | int | float | bool | None] = field(default_factory=dict)

    @property
    def is_synthetic_collapsed(self) -> bool:
        """Indicates whether this step is a collapsed synthesis of multiple steps."""
        return self.collapsed_count > 1

    def to_dict(self) -> dict[str, str | int | float | bool | None | dict[str, str | int | float | bool | None]]:
        """Normalize into a JSON-serializable dictionary."""
        return {
            "step_id": self.step_id,
            "run_id": self.run_id,
            "step_type": self.step_type.value,
            "content": self.content,
            "timestamp": self.timestamp,
            "return_code": self.return_code,
            "collapsed_count": self.collapsed_count,
            "duration_seconds": round(self.duration_seconds, 2),
            "first_timestamp": self.first_timestamp,
            "last_timestamp": self.last_timestamp,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class CollapseWindowConfig:
    """Configuration settings for collapse-before-cut stream windowing."""

    target_window_size: int = 20
    raw_tail_bound: int = 500
    prune_idle_finals: bool = True
    prune_redundant_observations: bool = True
    filter_ephemeral_reasoning: bool = True

    def __post_init__(self) -> None:
        if self.target_window_size <= 0:
            raise ValueError(f"target_window_size must be positive, got {self.target_window_size}")
        if self.raw_tail_bound < self.target_window_size:
            raise ValueError(
                f"raw_tail_bound ({self.raw_tail_bound}) cannot be less than target_window_size ({self.target_window_size})"
            )


@dataclass(frozen=True)
class CollapseWindowReceipt:
    """Cryptographically verifiable audit receipt of collapse-before-cut window transformation."""

    receipt_id: str
    raw_step_count: int
    pruned_step_count: int
    collapsed_idle_count: int
    effective_count_before_cut: int
    final_window_count: int
    tail_actions_preserved_count: int
    compression_ratio: float
    audit_checksum: str
    timestamp: float = field(default_factory=time.time)

    @classmethod
    def create(
        cls,
        *,
        receipt_id: str,
        raw_step_count: int,
        pruned_step_count: int,
        collapsed_idle_count: int,
        effective_count_before_cut: int,
        final_window_count: int,
        tail_actions_preserved_count: int,
    ) -> CollapseWindowReceipt:
        ratio = (
            round(1.0 - (final_window_count / raw_step_count), 4)
            if raw_step_count > 0
            else 0.0
        )
        payload = {
            "receipt_id": receipt_id,
            "raw_step_count": raw_step_count,
            "pruned_step_count": pruned_step_count,
            "collapsed_idle_count": collapsed_idle_count,
            "effective_count_before_cut": effective_count_before_cut,
            "final_window_count": final_window_count,
            "tail_actions_preserved_count": tail_actions_preserved_count,
            "compression_ratio": ratio,
        }
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        chk = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        return cls(
            receipt_id=receipt_id,
            raw_step_count=raw_step_count,
            pruned_step_count=pruned_step_count,
            collapsed_idle_count=collapsed_idle_count,
            effective_count_before_cut=effective_count_before_cut,
            final_window_count=final_window_count,
            tail_actions_preserved_count=tail_actions_preserved_count,
            compression_ratio=ratio,
            audit_checksum=chk,
        )
