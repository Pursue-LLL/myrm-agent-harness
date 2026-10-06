"""Context compaction visual observation and host-owned prompt accounting engine.

Implements:
1. HostOwnedPromptAccountingLedger: Accurate deduction and independent accounting
   of incompressible host-owned prompts (system prompt, tool schemas, skills, guidelines).
2. CompactionHysteresisBufferController: Dual-watermark smoothing buffer
   (high-watermark trigger, low-watermark target, deadband and cooldown turns)
   to completely eliminate critical threshold fluttering and cache thrashing.
3. CompactionObservationCollector: Structured observation payload with
   RetainedFrameSequence visualization and telemetry reporting.

[INPUT]
- langchain_core.messages.BaseMessage
- Sequence[BaseMessage]
- HostPromptBudgetSpec

[OUTPUT]
- HostOwnedPromptAccountingLedger
- CompactionHysteresisBufferController
- CompactionDecision
- RetainedFrameDescriptor
- CompactionObservationPayload
- CompactionObservationCollector

[POS]
Harness runtime context layer. Delivers deterministic host overhead separation,
anti-fluttering hysteresis control, and visual compaction telemetry.
"""

from __future__ import annotations

import math
import time
import uuid
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Final

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    SystemMessage,
    ToolMessage,
)

from myrm_agent_harness.utils.token_estimation import (
    estimate_message_tokens,
    estimate_tokens,
)

DEFAULT_HIGH_WATERMARK_RATIO: Final[float] = 0.80
DEFAULT_LOW_WATERMARK_RATIO: Final[float] = 0.55
DEFAULT_MIN_REDUCTION_TOKENS: Final[int] = 3000
DEFAULT_COOLDOWN_TURNS: Final[int] = 2
DEFAULT_SAFETY_RESERVE_TOKENS: Final[int] = 4096


class CompactionTriggerMode(StrEnum):
    """Reason triggering the context compaction operation."""

    HIGH_WATERMARK = "high_watermark"
    EMERGENCY_OVERFLOW = "emergency_overflow"
    MANUAL_INSTRUCTION = "manual_instruction"
    BACKGROUND_DRAIN = "background_drain"


class FrameCategory(StrEnum):
    """Categorization of messages within the retained context window."""

    SYSTEM_ANCHOR = "system_anchor"
    CHECKPOINT_SUMMARY = "checkpoint_summary"
    ACTIVE_TURN = "active_turn"
    TOOL_PAIRING = "tool_pairing"


@dataclass(slots=True, frozen=True)
class HostOwnedBreakdown:
    """Detailed breakdown of host-owned incompressible prompt overhead."""

    system_prompt_tokens: int = 0
    tool_schemas_tokens: int = 0
    skill_guidelines_tokens: int = 0
    environment_meta_tokens: int = 0

    @property
    def total_host_owned_tokens(self) -> int:
        """Sum of all host-owned incompressible overheads."""
        return (
            self.system_prompt_tokens
            + self.tool_schemas_tokens
            + self.skill_guidelines_tokens
            + self.environment_meta_tokens
        )


@dataclass(slots=True, frozen=True)
class HostOwnedPromptAccountingLedger:
    """Ledger tracking host-owned prompt overhead and effective conversational capacity."""

    model_context_window: int
    breakdown: HostOwnedBreakdown
    safety_reserve_tokens: int = DEFAULT_SAFETY_RESERVE_TOKENS

    @property
    def total_host_owned_tokens(self) -> int:
        """Total tokens claimed by the host environment."""
        return self.breakdown.total_host_owned_tokens

    @property
    def effective_compactable_capacity(self) -> int:
        """Net tokens available exclusively for dynamic compactable messages."""
        unclamped = (
            self.model_context_window
            - self.total_host_owned_tokens
            - self.safety_reserve_tokens
        )
        return max(1000, unclamped)

    @classmethod
    def calculate_from_sources(
        cls,
        *,
        model_context_window: int,
        system_prompt: str = "",
        tool_schemas_json: str = "",
        skill_guidelines: str = "",
        environment_meta: str = "",
        safety_reserve_tokens: int = DEFAULT_SAFETY_RESERVE_TOKENS,
    ) -> HostOwnedPromptAccountingLedger:
        """Construct ledger by estimating tokens across host sources."""
        breakdown = HostOwnedBreakdown(
            system_prompt_tokens=estimate_tokens(system_prompt) if system_prompt else 0,
            tool_schemas_tokens=estimate_tokens(tool_schemas_json) if tool_schemas_json else 0,
            skill_guidelines_tokens=estimate_tokens(skill_guidelines) if skill_guidelines else 0,
            environment_meta_tokens=estimate_tokens(environment_meta) if environment_meta else 0,
        )
        return cls(
            model_context_window=model_context_window,
            breakdown=breakdown,
            safety_reserve_tokens=safety_reserve_tokens,
        )


@dataclass(slots=True, frozen=True)
class CompactionDecision:
    """Decision outcome evaluated by the hysteresis buffer controller."""

    should_compact: bool
    trigger_mode: CompactionTriggerMode | None
    current_compactable_tokens: int
    high_watermark_tokens: int
    target_low_watermark_tokens: int
    tokens_to_reduce: int
    reason: str
    in_cooldown: bool = False
    cooldown_remaining_turns: int = 0


@dataclass(slots=True)
class CompactionHysteresisBufferController:
    """Dual-watermark hysteresis controller preventing threshold fluttering.

    Maintains separate high and low watermarks relative to effective capacity,
    enforces minimum reduction deadband, and tracks turn cooldowns.
    """

    high_watermark_ratio: float = DEFAULT_HIGH_WATERMARK_RATIO
    low_watermark_ratio: float = DEFAULT_LOW_WATERMARK_RATIO
    min_reduction_tokens: int = DEFAULT_MIN_REDUCTION_TOKENS
    cooldown_turns: int = DEFAULT_COOLDOWN_TURNS
    last_compaction_turn: int = -1

    def evaluate(
        self,
        *,
        current_compactable_tokens: int,
        current_turn: int,
        ledger: HostOwnedPromptAccountingLedger,
        force_emergency: bool = False,
    ) -> CompactionDecision:
        """Evaluate whether compaction must be executed."""
        effective_capacity = ledger.effective_compactable_capacity
        high_threshold = math.floor(effective_capacity * self.high_watermark_ratio)
        low_target = math.floor(effective_capacity * self.low_watermark_ratio)
        tokens_over_low = max(0, current_compactable_tokens - low_target)

        # 1. Emergency overflow path: bypasses cooldown and deadband
        if force_emergency or current_compactable_tokens >= effective_capacity:
            return CompactionDecision(
                should_compact=True,
                trigger_mode=CompactionTriggerMode.EMERGENCY_OVERFLOW,
                current_compactable_tokens=current_compactable_tokens,
                high_watermark_tokens=high_threshold,
                target_low_watermark_tokens=low_target,
                tokens_to_reduce=tokens_over_low,
                reason="Context exceeded effective capacity; emergency compaction triggered.",
            )

        # 2. Below high watermark: no compaction needed
        if current_compactable_tokens < high_threshold:
            return CompactionDecision(
                should_compact=False,
                trigger_mode=None,
                current_compactable_tokens=current_compactable_tokens,
                high_watermark_tokens=high_threshold,
                target_low_watermark_tokens=low_target,
                tokens_to_reduce=0,
                reason="Current compactable tokens below high watermark.",
            )

        # 3. Check cooldown turn window to prevent fluttering
        turns_since_last = current_turn - self.last_compaction_turn
        if self.last_compaction_turn >= 0 and turns_since_last < self.cooldown_turns:
            remaining = self.cooldown_turns - turns_since_last
            return CompactionDecision(
                should_compact=False,
                trigger_mode=None,
                current_compactable_tokens=current_compactable_tokens,
                high_watermark_tokens=high_threshold,
                target_low_watermark_tokens=low_target,
                tokens_to_reduce=0,
                reason=f"Compaction suppressed by cooldown buffer ({remaining} turns remaining).",
                in_cooldown=True,
                cooldown_remaining_turns=remaining,
            )

        # 4. Check deadband: avoid minor trimming if reduction is below threshold
        if tokens_over_low < self.min_reduction_tokens:
            return CompactionDecision(
                should_compact=False,
                trigger_mode=None,
                current_compactable_tokens=current_compactable_tokens,
                high_watermark_tokens=high_threshold,
                target_low_watermark_tokens=low_target,
                tokens_to_reduce=tokens_over_low,
                reason=f"Estimated token reduction ({tokens_over_low}) is below deadband threshold ({self.min_reduction_tokens}).",
            )

        # 5. Normal high-watermark compaction trigger
        return CompactionDecision(
            should_compact=True,
            trigger_mode=CompactionTriggerMode.HIGH_WATERMARK,
            current_compactable_tokens=current_compactable_tokens,
            high_watermark_tokens=high_threshold,
            target_low_watermark_tokens=low_target,
            tokens_to_reduce=tokens_over_low,
            reason="Current compactable tokens exceeded high watermark; smoothly reducing to low watermark.",
        )

    def record_compaction_performed(self, turn: int) -> None:
        """Update last compaction turn tracker to activate cooldown."""
        self.last_compaction_turn = turn


@dataclass(slots=True, frozen=True)
class RetainedFrameDescriptor:
    """Visual inspection descriptor for a single message frame retained in memory."""

    frame_index: int
    message_type: str
    role: str
    token_count: int
    category: FrameCategory
    preview_snippet: str


@dataclass(slots=True, frozen=True)
class CompactionObservationPayload:
    """Comprehensive visual observation and telemetry payload for compaction events."""

    event_id: str
    session_id: str
    timestamp: float
    trigger_mode: CompactionTriggerMode
    tokens_before: int
    tokens_after: int
    tokens_saved: int
    compression_ratio_pct: float
    duration_ms: float
    host_owned_breakdown: HostOwnedBreakdown
    effective_compactable_capacity: int
    archived_message_count: int
    archived_tokens: int
    retained_frames: tuple[RetainedFrameDescriptor, ...]

    def to_dict(self) -> dict[str, object]:
        """Convert telemetry payload into json-serializable dictionary."""
        payload_dict: dict[str, object] = {
            "event_id": self.event_id,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "trigger_mode": self.trigger_mode.value,
            "tokens_before": self.tokens_before,
            "tokens_after": self.tokens_after,
            "tokens_saved": self.tokens_saved,
            "compression_ratio_pct": self.compression_ratio_pct,
            "duration_ms": self.duration_ms,
            "host_owned_breakdown": asdict(self.host_owned_breakdown),
            "effective_compactable_capacity": self.effective_compactable_capacity,
            "archived_message_count": self.archived_message_count,
            "archived_tokens": self.archived_tokens,
            "retained_frames": [asdict(f) for f in self.retained_frames],
        }
        return payload_dict


class CompactionObservationCollector:
    """Builds visual observation records and retained frame sequences."""

    @staticmethod
    def classify_frame(message: BaseMessage, index: int) -> FrameCategory:
        """Determine frame classification category."""
        if isinstance(message, SystemMessage):
            return FrameCategory.SYSTEM_ANCHOR
        if isinstance(message, ToolMessage) or (
            isinstance(message, AIMessage) and bool(getattr(message, "tool_calls", None))
        ):
            return FrameCategory.TOOL_PAIRING
        content_str = str(message.content or "")
        if "previous-summary" in content_str.lower() or "checkpoint" in content_str.lower():
            return FrameCategory.CHECKPOINT_SUMMARY
        return FrameCategory.ACTIVE_TURN

    @classmethod
    def build_retained_frames(
        cls,
        messages: Sequence[BaseMessage],
        *,
        max_preview_len: int = 120,
    ) -> tuple[RetainedFrameDescriptor, ...]:
        """Construct sequence of retained frame descriptors from retained messages."""
        descriptors: list[RetainedFrameDescriptor] = []
        for idx, msg in enumerate(messages):
            tokens = estimate_message_tokens(msg)
            category = cls.classify_frame(msg, idx)
            content_str = str(msg.content or "").strip()
            snippet = (
                content_str[:max_preview_len] + "..."
                if len(content_str) > max_preview_len
                else content_str
            )
            role = getattr(msg, "role", None) or type(msg).__name__.replace("Message", "").lower()
            descriptors.append(
                RetainedFrameDescriptor(
                    frame_index=idx,
                    message_type=type(msg).__name__,
                    role=role,
                    token_count=tokens,
                    category=category,
                    preview_snippet=snippet,
                )
            )
        return tuple(descriptors)

    @classmethod
    def create_observation_payload(
        cls,
        *,
        session_id: str,
        trigger_mode: CompactionTriggerMode,
        tokens_before: int,
        tokens_after: int,
        duration_ms: float,
        ledger: HostOwnedPromptAccountingLedger,
        archived_message_count: int,
        retained_messages: Sequence[BaseMessage],
    ) -> CompactionObservationPayload:
        """Create a complete structured telemetry payload."""
        tokens_saved = max(0, tokens_before - tokens_after)
        ratio_pct = round((tokens_saved / tokens_before * 100.0), 2) if tokens_before > 0 else 0.0
        archived_tokens = tokens_saved  # Exact net tokens evicted to checkpoint/summary
        retained_frames = cls.build_retained_frames(retained_messages)

        return CompactionObservationPayload(
            event_id=f"cmp-{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            timestamp=time.time(),
            trigger_mode=trigger_mode,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            tokens_saved=tokens_saved,
            compression_ratio_pct=ratio_pct,
            duration_ms=duration_ms,
            host_owned_breakdown=ledger.breakdown,
            effective_compactable_capacity=ledger.effective_compactable_capacity,
            archived_message_count=archived_message_count,
            archived_tokens=archived_tokens,
            retained_frames=retained_frames,
        )
