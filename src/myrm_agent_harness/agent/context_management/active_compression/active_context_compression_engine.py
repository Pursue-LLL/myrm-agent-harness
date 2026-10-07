"""Core implementation of Active-Turn Live Context Compression Engine.

Provides microsecond token pressure gauging, slash command /compress detection,
lossless anchor preservation, and structured middle trajectory folding.
"""

from __future__ import annotations

import logging
import threading
import time

from .active_compression_types import (
    ActiveCompressionConfig,
    ActiveCompressionResult,
    CompressTriggerKind,
    TokenPressureLevel,
    TokenPressureSnapshot,
)

logger = logging.getLogger(__name__)


def approximate_tokens_for_message(msg: dict[str, str]) -> int:
    """Rough token estimation (~4 chars per token) without external heavy deps."""
    content = msg.get("content", "")
    return max(1, len(content) // 4)


def approximate_tokens_for_messages(messages: tuple[dict[str, str], ...] | list[dict[str, str]]) -> int:
    """Sum approximate tokens across all message envelopes."""
    return sum(approximate_tokens_for_message(m) for m in messages)


class TokenPressureGauge:
    """High-performance token pressure evaluator providing real-time HUD telemetry."""

    @staticmethod
    def measure(
        current_tokens: int,
        config: ActiveCompressionConfig | None = None,
    ) -> TokenPressureSnapshot:
        """Measure current context pressure against context budget."""
        cfg = config or ActiveCompressionConfig()
        limit = max(1, cfg.context_limit)
        ratio = round(current_tokens / limit, 4)

        if ratio >= cfg.critical_watermark_ratio:
            level = TokenPressureLevel.CRITICAL
            rec_compress = True
            status_text = f"🚨 上下文已达到极限 ({int(ratio * 100)}%)，正在自动进行无感压缩"
        elif ratio >= cfg.high_watermark_ratio:
            level = TokenPressureLevel.HIGH
            rec_compress = True
            status_text = f"⚠️ 会话历史较长 ({int(ratio * 100)}%)，响应可能变慢，建议点击压缩"
        elif ratio >= 0.50:
            level = TokenPressureLevel.MODERATE
            rec_compress = False
            status_text = f"⚡ 上下文正常负载 ({int(ratio * 100)}%)"
        else:
            level = TokenPressureLevel.NORMAL
            rec_compress = False
            status_text = f"🟢 上下文极速模式 ({int(ratio * 100)}%)"

        # Model non-linear TTFT latency expansion at higher context depths
        base_ttft = 1.2
        latency = round(base_ttft + (ratio**1.8) * 16.0, 2)

        return TokenPressureSnapshot(
            current_tokens=current_tokens,
            context_limit=limit,
            usage_ratio=ratio,
            pressure_level=level,
            estimated_latency_seconds=latency,
            recommend_compression=rec_compress,
            status_text=status_text,
        )


class ActiveContextCompressionEngine:
    """Executes high-fidelity active context compression preserving system anchors and memory."""

    def __init__(self, config: ActiveCompressionConfig | None = None) -> None:
        self._config = config or ActiveCompressionConfig()
        self._lock = threading.RLock()

    @staticmethod
    def is_compress_command(user_text: str) -> bool:
        """Inspect if the incoming prompt is a slash command requesting context compaction."""
        cleaned = user_text.strip().lower()
        return cleaned in ("/compress", "/compact", "/compress now", "/compact now") or cleaned.startswith(
            ("/compress ", "/compact ")
        )

    def execute_compression(
        self,
        messages: list[dict[str, str]] | tuple[dict[str, str], ...],
        trigger_kind: CompressTriggerKind = CompressTriggerKind.USER_EXPLICIT_SLASH,
    ) -> ActiveCompressionResult:
        """Compress intermediate conversation turns while preserving anchors and latest tail."""
        start_t = time.perf_counter()
        with self._lock:
            original_tokens = approximate_tokens_for_messages(messages)
            msg_list = list(messages)
            total_msgs = len(msg_list)

            # If message chain is too brief to partition safely, return as-is
            min_required = self._config.keep_head_turns + self._config.keep_tail_turns + 1
            if total_msgs < min_required:
                duration_ms = (time.perf_counter() - start_t) * 1000.0
                return ActiveCompressionResult(
                    is_compressed=False,
                    trigger_kind=trigger_kind,
                    original_tokens=original_tokens,
                    compacted_tokens=original_tokens,
                    reclaimed_tokens=0,
                    reclaim_ratio=0.0,
                    frozen_head_count=total_msgs,
                    preserved_tail_count=0,
                    folded_middle_count=0,
                    compacted_messages=tuple(msg_list),
                    duration_ms=round(duration_ms, 2),
                )

            # Partition into head (frozen), middle (foldable), tail (preserved)
            head_count = self._config.keep_head_turns
            tail_count = self._config.keep_tail_turns

            head_slice = msg_list[:head_count]
            middle_slice = msg_list[head_count : total_msgs - tail_count]
            tail_slice = msg_list[total_msgs - tail_count :]

            # Fold middle turns into high-signal structured state summary
            folded_summary = self._synthesize_middle_state_summary(middle_slice)
            summary_message: dict[str, str] = {
                "role": "system",
                "content": folded_summary,
            }

            compacted_list: list[dict[str, str]] = list(head_slice)
            compacted_list.append(summary_message)
            compacted_list.extend(tail_slice)

            compacted_tokens = approximate_tokens_for_messages(compacted_list)
            reclaimed = max(0, original_tokens - compacted_tokens)
            reclaim_ratio = round(reclaimed / original_tokens, 4) if original_tokens > 0 else 0.0
            duration_ms = (time.perf_counter() - start_t) * 1000.0

            logger.info(
                "Active compression executed via %s: %d -> %d tokens (reclaimed %d, ratio %.2f%%)",
                trigger_kind.value,
                original_tokens,
                compacted_tokens,
                reclaimed,
                reclaim_ratio * 100.0,
            )

            return ActiveCompressionResult(
                is_compressed=True,
                trigger_kind=trigger_kind,
                original_tokens=original_tokens,
                compacted_tokens=compacted_tokens,
                reclaimed_tokens=reclaimed,
                reclaim_ratio=reclaim_ratio,
                frozen_head_count=len(head_slice),
                preserved_tail_count=len(tail_slice),
                folded_middle_count=len(middle_slice),
                compacted_messages=tuple(compacted_list),
                duration_ms=round(duration_ms, 2),
            )

    def _synthesize_middle_state_summary(self, middle_slice: list[dict[str, str]]) -> str:
        """Synthesize verbose tool executions and dialogues into compact structured progress."""
        executed_steps: list[str] = []
        key_findings: list[str] = []

        for idx, msg in enumerate(middle_slice):
            role = msg.get("role", "unknown")
            content = msg.get("content", "").strip()
            # Capture tool executions or user directives concisely
            if role in ("tool", "function"):
                snippet = content[:80].replace("\n", " ")
                executed_steps.append(f"Tool executed step #{idx + 1}: {snippet}...")
            elif role == "user":
                snippet = content[:100].replace("\n", " ")
                key_findings.append(f"User instruction: {snippet}")
            elif role == "assistant":
                snippet = content[:120].replace("\n", " ")
                key_findings.append(f"Assistant conclusion: {snippet}...")

        summary_lines = [
            "[ACTIVE CONTEXT RECLAIMED STATE SNAPSHOT]",
            f"- Folded Turns: {len(middle_slice)} intermediate execution messages compactified.",
        ]
        if key_findings:
            summary_lines.append("- Intermediate Directives & Conclusions:")
            summary_lines.extend(f"  • {item}" for item in key_findings[:5])
        if executed_steps:
            summary_lines.append("- Executed Tool Actions:")
            summary_lines.extend(f"  • {step}" for step in executed_steps[:5])
        summary_lines.append("- Status: All baseline intentions maintained; detailed logs pruned.")

        return "\n".join(summary_lines)
