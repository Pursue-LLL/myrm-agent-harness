"""Engine and Meta-Tool Factory for Context Cognitive Gauge and Agent Self-Awareness.

Part of Item 125: InspectContextCognitiveGaugeMetaTool.
Provides real-time cognitive capacity inspection, dynamic headroom estimation,
and the callable inspect_context meta-tool for autonomous agent regulation.

[INPUT]
- runtime.context.context_cognitive_gauge_types::CognitiveActionGuidance, CognitiveGaugeConfig,
  ContextCognitiveSnapshot, ContextUrgencyLevel (POS: Types and models for Context Cognitive Gauge and Agent
  Context Self-Awareness.)
- utils.locale::is_chinese (POS: Shared locale utilities consumed by channel i18n, error diagnostics, and
  component text fallbacks. Single source of truth for locale string handling.)
- utils.token_estimation::estimate_context_tokens (POS: Token estimation infrastructure. Covers
  message-level tokens and bind-tools overhead for context budget / compress / summarize decisions. Aligns
  with measure_turn1_token_inventory planning SSOT.)

[OUTPUT]
- ContextCognitiveGauge: Core engine evaluating agent cognitive headroom and context burn rate.
- create_inspect_context_tool(): Factory creating the inspect_context Meta-Tool for agent integration.

[POS]
Engine and Meta-Tool Factory for Context Cognitive Gauge and Agent Self-Awareness.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Sequence
from typing import Final

from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool, tool

from myrm_agent_harness.runtime.context.context_cognitive_gauge_types import (
    CognitiveActionGuidance,
    CognitiveGaugeConfig,
    ContextCognitiveSnapshot,
    ContextUrgencyLevel,
)
from myrm_agent_harness.utils.locale import is_chinese
from myrm_agent_harness.utils.token_estimation import estimate_context_tokens

logger = logging.getLogger(__name__)

INSPECT_CONTEXT_TOOL_DESC_EN: Final[str] = (
    "Inspect the agent's current cognitive capacity, remaining token headroom, "
    "and recommended behavioral discipline. Call this tool when planning complex "
    "multi-step reasoning, before reading large files, or when sensing a long session "
    "to check if you need to converge, brake, or summarize findings."
)

INSPECT_CONTEXT_TOOL_DESC_ZH: Final[str] = (
    "自查当前会话的上下文认知油量表、剩余 Token 余量及行为收敛指引。"
    "在开启复杂长步骤规划、读取超大文件或长程任务中主动调用，"
    "以此了解剩余脑容量，自主决定是继续发散探索，还是及时踩刹车并沉淀阶段性结论。"
)


class ContextCognitiveGauge:
    """Core engine evaluating agent cognitive headroom and context burn rate."""

    def __init__(self, config: CognitiveGaugeConfig | None = None) -> None:
        self._config = config or CognitiveGaugeConfig()
        self._lock = threading.Lock()
        self._turn_burn_history: list[int] = []

    @property
    def config(self) -> CognitiveGaugeConfig:
        """Get the active configuration."""
        return self._config

    def record_turn_burn(self, tokens_consumed: int) -> None:
        """Record the token burn of a single turn to update dynamic turn burn rate."""
        if tokens_consumed <= 0:
            return
        with self._lock:
            self._turn_burn_history.append(tokens_consumed)
            if len(self._turn_burn_history) > self._config.max_history_turns_tracked:
                self._turn_burn_history.pop(0)

    def get_average_turn_burn(self) -> int:
        """Calculate weighted or moving average burn rate per turn."""
        with self._lock:
            if not self._turn_burn_history:
                return self._config.default_turn_token_burn
            return max(1, sum(self._turn_burn_history) // len(self._turn_burn_history))

    def _render_gauge_bar(self, capacity_pct: float, width: int = 16) -> str:
        """Render a text-based HUD gauge bar."""
        clamped_pct = max(0.0, min(100.0, capacity_pct))
        filled_slots = round((clamped_pct / 100.0) * width)
        filled_slots = max(0, min(width, filled_slots))
        empty_slots = width - filled_slots
        return f"[{'█' * filled_slots}{'░' * empty_slots}] {clamped_pct:.1f}%"

    def inspect(
        self,
        used_tokens: int,
        max_tokens: int | None = None,
    ) -> ContextCognitiveSnapshot:
        """Produce an immutable snapshot from an explicit token count."""
        limit = max_tokens if max_tokens is not None and max_tokens > 0 else self._config.max_context_tokens
        safe_used = max(0, used_tokens)
        remaining = max(0, limit - safe_used)
        pct = round(min(100.0, (safe_used / limit) * 100.0), 2)

        avg_burn = self.get_average_turn_burn()
        remaining_turns = remaining // avg_burn if avg_burn > 0 else 0

        # Determine urgency tier and guidance
        if pct < self._config.converging_threshold_pct:
            urgency = ContextUrgencyLevel.NOMINAL
            action = CognitiveActionGuidance.EXPLORE_FREELY
            guidance = (
                f"Headroom abundant ({pct:.1f}% used, ~{remaining_turns} turns left). "
                "Feel free to explore and perform multi-step analysis."
            )
        elif pct < self._config.critical_threshold_pct:
            urgency = ContextUrgencyLevel.CONVERGING
            action = CognitiveActionGuidance.CONVERGE_AND_VERIFY
            guidance = (
                f"Context reaching saturation ({pct:.1f}% used, ~{remaining_turns} turns left). "
                "Begin converging subtasks, avoid unbounded broad queries, and prepare verification."
            )
        elif pct < self._config.exhausted_threshold_pct:
            urgency = ContextUrgencyLevel.CRITICAL
            action = CognitiveActionGuidance.BRAKE_AND_SUMMARIZE
            guidance = (
                f"Context critical ({pct:.1f}% used, ~{remaining_turns} turns left)! "
                "Brake immediately: stop reading new files, write structured findings, and consolidate notes."
            )
        else:
            urgency = ContextUrgencyLevel.EXHAUSTED
            action = CognitiveActionGuidance.EMERGENCY_HANDOFF
            guidance = (
                f"Context capacity exhausted ({pct:.1f}% used)! "
                "Emergency handoff: emit concise answer or state-transfer memo immediately."
            )

        imminent_threshold = max(0.0, self._config.critical_threshold_pct - 10.0)
        is_compaction_imminent = (pct >= imminent_threshold) or (remaining_turns <= 2)

        return ContextCognitiveSnapshot(
            total_limit_tokens=limit,
            used_tokens=safe_used,
            remaining_tokens=remaining,
            capacity_pct=pct,
            urgency_level=urgency,
            suggested_action=action,
            estimated_remaining_turns=remaining_turns,
            is_compaction_imminent=is_compaction_imminent,
            gauge_rendered_bar=self._render_gauge_bar(pct),
            guidance_message=guidance,
        )

    def inspect_from_messages(
        self,
        messages: Sequence[BaseMessage],
        max_tokens: int | None = None,
    ) -> ContextCognitiveSnapshot:
        """Estimate tokens directly from a message list and produce a snapshot."""
        estimated = estimate_context_tokens(list(messages))
        return self.inspect(used_tokens=estimated, max_tokens=max_tokens)


def create_inspect_context_tool(
    gauge: ContextCognitiveGauge | None = None,
    locale: str = "en",
) -> BaseTool:
    """Factory creating the inspect_context Meta-Tool for agent integration."""
    active_gauge = gauge or ContextCognitiveGauge()
    description = INSPECT_CONTEXT_TOOL_DESC_ZH if is_chinese(locale) else INSPECT_CONTEXT_TOOL_DESC_EN

    @tool("inspect_context", description=description)
    def inspect_context(
        current_used_tokens: int | None = None,
    ) -> str:
        """Inspect the agent's current context gauge and cognitive budget.

        Args:
            current_used_tokens: Optional token estimate override. If omitted,
                                 evaluates based on registered gauge state.
        """
        used = current_used_tokens if current_used_tokens is not None else 0
        snapshot = active_gauge.inspect(used_tokens=used)
        result_dict = snapshot.model_dump(mode="json")
        return json.dumps(result_dict, ensure_ascii=False)

    return inspect_context
