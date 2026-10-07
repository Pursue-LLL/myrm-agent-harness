"""Lean-Tail Boundary Compactor implementing strict head/tail preservation.

Enforces protect_first_n (e.g. system instructions, persona, core constraints)
and protect_last_n (e.g. recent task execution, active tool outputs) while
intelligently summarizing intermediate historical messages.

[INPUT]
- runtime.context.context_lifecycle_visualizer_types::ContextLifecycleSectionReport, ContextSectionKind,
  ContextSectionSlice, LeanTailBoundaryConfig (POS: Data contracts and schemas for Lean-Tail Context
  Lifecycle and Visualizer.)

[OUTPUT]
- LeanTailBoundaryCompactor: Compactor enforcing verbatim head/tail protection and middle summarization.

[POS]
Lean-Tail Boundary Compactor implementing strict head/tail preservation.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from myrm_agent_harness.runtime.context.context_lifecycle_visualizer_types import (
    ContextLifecycleSectionReport,
    ContextSectionKind,
    ContextSectionSlice,
    LeanTailBoundaryConfig,
)

_ANCHOR_PATTERNS: tuple[str, ...] = (
    "约定",
    "决定",
    "确认",
    "目标",
    "配置",
    "完成",
    "待办",
    "修复",
    "agreement",
    "decision",
    "todo",
    "config",
)


class LeanTailBoundaryCompactor:
    """Compactor enforcing verbatim head/tail protection and middle summarization."""

    def __init__(self, config: LeanTailBoundaryConfig | None = None) -> None:
        self._config = config or LeanTailBoundaryConfig()

    def compact(
        self,
        messages: Sequence[dict[str, str]],
        session_id: str,
        *,
        context_window_size: int = 128_000,
        estimated_total_tokens: int | None = None,
    ) -> tuple[list[dict[str, str]], ContextLifecycleSectionReport]:
        """Split into head, middle, tail, compressing only middle when threshold is met."""
        msg_list: list[dict[str, str]] = [dict(m) for m in messages]
        total_msgs = len(msg_list)
        total_tokens = (
            estimated_total_tokens
            if estimated_total_tokens is not None
            else self.estimate_tokens(msg_list)
        )

        trigger_tokens = int(
            context_window_size * self._config.trigger_threshold_ratio
        )
        min_boundary = (
            self._config.protect_first_n
            + self._config.protect_last_n
            + self._config.min_middle_messages_to_compress
        )

        # Check whether compaction should trigger
        if total_msgs < min_boundary or total_tokens < trigger_tokens:
            return msg_list, self._build_uncompacted_report(
                session_id=session_id,
                messages=msg_list,
                total_tokens=total_tokens,
            )

        # Slice into three strictly demarcated segments
        head_msgs = msg_list[: self._config.protect_first_n]
        tail_msgs = msg_list[-self._config.protect_last_n :]
        middle_msgs = msg_list[
            self._config.protect_first_n : -self._config.protect_last_n
        ]

        head_tokens = self.estimate_tokens(head_msgs)
        tail_tokens = self.estimate_tokens(tail_msgs)
        middle_tokens = self.estimate_tokens(middle_msgs)

        # Extract essential anchors and generate middle summary
        anchors = self._extract_key_anchors(middle_msgs)
        summary_text = self._synthesize_middle_summary(middle_msgs, anchors)
        summary_msg: dict[str, str] = {
            "role": "user",
            "content": (
                "<compacted_middle_history>\n"
                f"{summary_text}\n"
                "</compacted_middle_history>"
            ),
        }
        compacted_middle_tokens = self.estimate_tokens([summary_msg])

        assembled_messages: list[dict[str, str]] = [
            *head_msgs,
            summary_msg,
            *tail_msgs,
        ]

        compacted_total_tokens = (
            head_tokens + compacted_middle_tokens + tail_tokens
        )
        saved_tokens = max(0, total_tokens - compacted_total_tokens)
        ratio = round(
            compacted_total_tokens / total_tokens if total_tokens > 0 else 1.0, 3
        )

        sections: list[ContextSectionSlice] = [
            ContextSectionSlice(
                kind=ContextSectionKind.HEAD_PROTECTED,
                message_count=len(head_msgs),
                original_tokens=head_tokens,
                compacted_tokens=head_tokens,
                is_compressed=False,
                key_elements=["系统设定与全局契约"],
            ),
            ContextSectionSlice(
                kind=ContextSectionKind.MIDDLE_COMPACTED,
                message_count=len(middle_msgs),
                original_tokens=middle_tokens,
                compacted_tokens=compacted_middle_tokens,
                is_compressed=True,
                summary_excerpt=summary_text[:160] + "...",
                key_elements=anchors[:5],
            ),
            ContextSectionSlice(
                kind=ContextSectionKind.TAIL_PROTECTED,
                message_count=len(tail_msgs),
                original_tokens=tail_tokens,
                compacted_tokens=tail_tokens,
                is_compressed=False,
                key_elements=["当前活跃执行轮次与最新工具输出"],
            ),
        ]

        report = ContextLifecycleSectionReport(
            session_id=session_id,
            total_messages_before=total_msgs,
            total_messages_after=len(assembled_messages),
            original_tokens=total_tokens,
            compacted_tokens=compacted_total_tokens,
            tokens_saved=saved_tokens,
            compression_ratio=ratio,
            sections=sections,
            retained_anchors=anchors,
            needs_compaction=True,
        )

        return assembled_messages, report

    def _extract_key_anchors(
        self, messages: Sequence[dict[str, str]]
    ) -> list[str]:
        """Harvest decisive agreements and milestones from middle messages."""
        anchors: list[str] = []
        for msg in messages:
            content = msg.get("content", "")
            lines = content.splitlines()
            for line in lines:
                clean_line = re.sub(r"\s+", " ", line).strip()
                if not clean_line or len(clean_line) < 6:
                    continue
                lower_line = clean_line.lower()
                if any(pat in lower_line for pat in _ANCHOR_PATTERNS):
                    anchors.append(clean_line[:120])
                    if len(anchors) >= 12:
                        return anchors
        return anchors

    def _synthesize_middle_summary(
        self, messages: Sequence[dict[str, str]], anchors: Sequence[str]
    ) -> str:
        """Construct structured summary block preserving critical decisions."""
        lines = [
            f"已压缩中间历史 {len(messages)} 条消息，保留核心执行上下文与关键约定：",
        ]
        if anchors:
            lines.append("【核心约定与结论保留】")
            for idx, a in enumerate(anchors[:8], 1):
                lines.append(f"{idx}. {a}")
        else:
            lines.append("- 中间执行阶段完成了相关辅助查询、代码编辑与状态确认。")
        return "\n".join(lines)

    def _build_uncompacted_report(
        self,
        session_id: str,
        messages: Sequence[dict[str, str]],
        total_tokens: int,
    ) -> ContextLifecycleSectionReport:
        """Generate audit report for context that does not require compaction."""
        section = ContextSectionSlice(
            kind=ContextSectionKind.TAIL_PROTECTED,
            message_count=len(messages),
            original_tokens=total_tokens,
            compacted_tokens=total_tokens,
            is_compressed=False,
            key_elements=["全量上下文处于安全预算内，免压缩保真"],
        )
        return ContextLifecycleSectionReport(
            session_id=session_id,
            total_messages_before=len(messages),
            total_messages_after=len(messages),
            original_tokens=total_tokens,
            compacted_tokens=total_tokens,
            tokens_saved=0,
            compression_ratio=1.0,
            sections=[section],
            retained_anchors=[],
            needs_compaction=False,
        )

    @staticmethod
    def estimate_tokens(messages: Sequence[dict[str, str]]) -> int:
        """Estimate token volume via character length heuristic (4 chars per token)."""
        return sum(max(1, len(m.get("content", "")) // 4) for m in messages)
