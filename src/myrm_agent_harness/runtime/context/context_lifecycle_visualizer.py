"""Context lifecycle visualizer rendering three-tier compression dashboards.

Transforms ContextLifecycleSectionReport payloads into UI-ready structured representations
and human-readable diagnostic status bars for frontend ContextUsageIndicator components.
"""

from __future__ import annotations

from typing import TypedDict

from myrm_agent_harness.runtime.context.context_lifecycle_visualizer_types import (
    ContextLifecycleSectionReport,
    ContextSectionKind,
)


class SectionUiItem(TypedDict):
    """Structured segment metadata consumable by WebUI/Desktop charts."""

    kind: str
    label: str
    message_count: int
    original_tokens: int
    compacted_tokens: int
    is_compressed: bool
    summary_excerpt: str | None
    key_elements: list[str]


class ContextLifecycleUiPayload(TypedDict):
    """Complete serialized payload for frontend context health components."""

    session_id: str
    total_messages_before: int
    total_messages_after: int
    original_tokens: int
    compacted_tokens: int
    tokens_saved: int
    savings_percentage: float
    sections: list[SectionUiItem]
    retained_anchors: list[str]
    needs_compaction: bool


class ContextLifecycleVisualizer:
    """Renderer and formatter for three-tier context lifecycle inspections."""

    @staticmethod
    def build_ui_payload(
        report: ContextLifecycleSectionReport,
    ) -> ContextLifecycleUiPayload:
        """Produce structured JSON payload for WebUI/Desktop context indicators."""
        label_map: dict[ContextSectionKind, str] = {
            ContextSectionKind.HEAD_PROTECTED: "头部保护区 (System & Constraints)",
            ContextSectionKind.MIDDLE_COMPACTED: "历史压缩区 (Compacted History)",
            ContextSectionKind.TAIL_PROTECTED: "活跃尾部保护区 (Active Execution)",
        }

        ui_sections: list[SectionUiItem] = [
            SectionUiItem(
                kind=sec.kind.value,
                label=label_map.get(sec.kind, sec.kind.value),
                message_count=sec.message_count,
                original_tokens=sec.original_tokens,
                compacted_tokens=sec.compacted_tokens,
                is_compressed=sec.is_compressed,
                summary_excerpt=sec.summary_excerpt,
                key_elements=list(sec.key_elements),
            )
            for sec in report.sections
        ]

        savings_pct = (
            round((report.tokens_saved / report.original_tokens) * 100.0, 1)
            if report.original_tokens > 0
            else 0.0
        )

        return ContextLifecycleUiPayload(
            session_id=report.session_id,
            total_messages_before=report.total_messages_before,
            total_messages_after=report.total_messages_after,
            original_tokens=report.original_tokens,
            compacted_tokens=report.compacted_tokens,
            tokens_saved=report.tokens_saved,
            savings_percentage=savings_pct,
            sections=ui_sections,
            retained_anchors=list(report.retained_anchors),
            needs_compaction=report.needs_compaction,
        )

    @staticmethod
    def render_ascii_dashboard(report: ContextLifecycleSectionReport) -> str:
        """Render a readable text-mode visual representation of the context tiers."""
        lines: list[str] = [
            "================= 上下文生命周期与三段式瘦身看板 =================",
            f"会话 ID: {report.session_id} | 触发压缩: {'是' if report.needs_compaction else '否'}",
            f"原始消息数: {report.total_messages_before} -> 现存消息数: {report.total_messages_after}",
            f"Token 占用: {report.original_tokens} -> {report.compacted_tokens} (节省: {report.tokens_saved} tokens)",
            "------------------------------------------------------------------",
        ]

        for sec in report.sections:
            tag = "🔒 [严格保护]" if not sec.is_compressed else "🗜️  [智能压缩]"
            lines.append(
                f"{tag} {sec.kind.value.upper()}: {sec.message_count} 条消息 | "
                f"{sec.original_tokens} -> {sec.compacted_tokens} tokens"
            )
            if sec.key_elements:
                elements_str = "、".join(sec.key_elements[:3])
                lines.append(f"   └─ 关键要素/锚点: {elements_str}")

        if report.retained_anchors:
            lines.append("------------------------------------------------------------------")
            lines.append(f"关键约定与待办保留项 (共 {len(report.retained_anchors)} 项):")
            for idx, item in enumerate(report.retained_anchors[:5], 1):
                lines.append(f"  {idx}. {item}")

        lines.append("==================================================================")
        return "\n".join(lines)
