"""
[INPUT]
- query: str (User conversational prompt or analytical inquiry)
- context_data: str | list[dict[str, str]] | None (Optional tabular or structured text payload)
- threshold: float (Minimum heuristic confidence to trigger autonomous visualization, defaults to 0.5)

[OUTPUT]
- VisualizationIntentResult containing trigger decision, category, confidence score, and matched signals

[POS]
Autonomous intent detector for ZeroPromptAutonomousVisualizationAndDynamicWebDashboardEngine (Item 49 P1).
Analyzes linguistic cues and tabular structures to trigger visual rendering without explicit user requests.
Strictly under 220 lines. Zero Any.
"""

import re
from typing import Final

from .visualization_types import (
    VisualizationCategory,
    VisualizationIntentResult,
)

# Intent signal dictionaries for pattern matching
_TREND_SIGNALS: Final[tuple[str, ...]] = (
    "走势", "趋势", "增长", "下降", "同比", "环比", "按月", "按年", "时序",
    "trend", "growth", "trajectory", "historical", "time series", "fluctuation",
)

_COMPARISON_SIGNALS: Final[tuple[str, ...]] = (
    "对比", "比较", "排名", "排行", "前十", "对照", "胜出", "优于",
    "vs", "compare", "comparison", "benchmark", "ranking", "versus", "top 10",
)

_PROPORTION_SIGNALS: Final[tuple[str, ...]] = (
    "占比", "份额", "构成", "比例", "分布", "百分比", "预算拆解",
    "proportion", "breakdown", "distribution", "share", "percentage", "allocation",
)

_FUNNEL_SIGNALS: Final[tuple[str, ...]] = (
    "漏斗", "转化率", "流失率", "转化链路", "转化环节", "留存",
    "funnel", "conversion", "drop-off", "retention", "pipeline conversion",
)

_TOPOLOGY_SIGNALS: Final[tuple[str, ...]] = (
    "架构", "拓扑", "调用链", "依赖关系", "网络拓扑", "节点关系",
    "topology", "architecture", "call graph", "dependency graph", "network diagram",
)

_DASHBOARD_SIGNALS: Final[tuple[str, ...]] = (
    "大盘", "看板", "仪表盘", "业务大盘", "监控看板", "经营概览", "多维数据",
    "dashboard", "overview", "cockpit", "kpi summary", "performance board",
)


class VisualizationIntentDetector:
    """Heuristic detector that recognizes analytical intent and triggers visual formats."""

    def __init__(self, min_confidence: float = 0.5) -> None:
        self.min_confidence = min_confidence

    def detect(
        self,
        query: str,
        context_data: str | list[dict[str, str]] | None = None,
    ) -> VisualizationIntentResult:
        """Evaluate query and accompanying data to decide if visualization should be triggered."""
        clean_text = query.strip().lower()

        # 0. Early short-circuit for explicit text-only requests
        negative_patterns = (
            "不要画图", "不要图", "不用画图", "不用图", "别画图", "别出图",
            "纯文字", "纯文本", "no chart", "no diagram", "just text", "text only",
        )
        if any(pat in clean_text for pat in negative_patterns):
            return VisualizationIntentResult(
                should_visualize=False,
                category=VisualizationCategory.NONE,
                confidence=0.0,
                matched_signals=["explicit_text_only_requested"],
            )

        matched_signals: list[str] = []

        # 1. Check for tabular structured evidence
        has_tabular_data = self._has_tabular_structure(context_data)
        if has_tabular_data:
            matched_signals.append("tabular_structure_detected")

        # 2. Score category affinities
        scores: dict[VisualizationCategory, float] = {
            VisualizationCategory.DATA_DASHBOARD: 0.0,
            VisualizationCategory.TREND_LINE: 0.0,
            VisualizationCategory.COMPARISON_BAR: 0.0,
            VisualizationCategory.PROPORTION_PIE: 0.0,
            VisualizationCategory.FUNNEL: 0.0,
            VisualizationCategory.TOPOLOGY_GRAPH: 0.0,
        }

        # Dashboard signals check
        for sig in _DASHBOARD_SIGNALS:
            if sig.lower() in clean_text:
                scores[VisualizationCategory.DATA_DASHBOARD] += 0.35
                matched_signals.append(f"dashboard:{sig}")

        # Trend signals check
        for sig in _TREND_SIGNALS:
            if sig.lower() in clean_text:
                scores[VisualizationCategory.TREND_LINE] += 0.3
                matched_signals.append(f"trend:{sig}")

        # Comparison signals check
        for sig in _COMPARISON_SIGNALS:
            if sig.lower() in clean_text:
                scores[VisualizationCategory.COMPARISON_BAR] += 0.3
                matched_signals.append(f"comparison:{sig}")

        # Proportion signals check
        for sig in _PROPORTION_SIGNALS:
            if sig.lower() in clean_text:
                scores[VisualizationCategory.PROPORTION_PIE] += 0.3
                matched_signals.append(f"proportion:{sig}")

        # Funnel signals check
        for sig in _FUNNEL_SIGNALS:
            if sig.lower() in clean_text:
                scores[VisualizationCategory.FUNNEL] += 0.4
                matched_signals.append(f"funnel:{sig}")

        # Topology signals check
        for sig in _TOPOLOGY_SIGNALS:
            if sig.lower() in clean_text:
                scores[VisualizationCategory.TOPOLOGY_GRAPH] += 0.35
                matched_signals.append(f"topology:{sig}")

        # If tabular data is present with multiple columns/rows, elevate Dashboard affinity
        if has_tabular_data:
            scores[VisualizationCategory.DATA_DASHBOARD] += 0.45
            scores[VisualizationCategory.COMPARISON_BAR] += 0.25

        # Find category with highest affinity
        best_category = max(scores, key=lambda k: scores[k])
        highest_score = min(scores[best_category], 1.0)

        should_trigger = highest_score >= self.min_confidence

        if not should_trigger:
            return VisualizationIntentResult(
                should_visualize=False,
                category=VisualizationCategory.NONE,
                confidence=highest_score,
                matched_signals=matched_signals,
            )

        # Infer title and suggested renderer
        recommended_title = self._derive_title(clean_text, best_category)
        suggested_renderer = "interactive_html" if best_category == VisualizationCategory.DATA_DASHBOARD else "svg"

        return VisualizationIntentResult(
            should_visualize=True,
            category=best_category,
            confidence=round(highest_score, 2),
            matched_signals=matched_signals,
            recommended_title=recommended_title,
            suggested_renderer=suggested_renderer,
        )

    def _has_tabular_structure(
        self,
        context_data: str | list[dict[str, str]] | None,
    ) -> bool:
        """Determine if context data represents tabular spreadsheet records."""
        if not context_data:
            return False

        if isinstance(context_data, list):
            return len(context_data) >= 2 and all(isinstance(r, dict) for r in context_data)

        if isinstance(context_data, str):
            lines = [l.strip() for l in context_data.strip().splitlines() if l.strip()]
            if len(lines) >= 3:
                # Markdown table format indicator
                if any("|" in l for l in lines) and any("---" in l for l in lines):
                    return True
                # CSV format indicator
                if sum(1 for l in lines if "," in l or "\t" in l) >= len(lines) * 0.7:
                    return True

        return False

    def _derive_title(self, query: str, category: VisualizationCategory) -> str:
        """Derive meaningful title from query and category."""
        clean = re.sub(r"[，。！？,\.!?]", " ", query).strip()
        words = clean.split()
        lead = " ".join(words[:4]) if words else "业务数据"
        category_map = {
            VisualizationCategory.TREND_LINE: "时序演变分析",
            VisualizationCategory.COMPARISON_BAR: "多维度对比分析",
            VisualizationCategory.PROPORTION_PIE: "构成与占比透视",
            VisualizationCategory.FUNNEL: "关键转化漏斗",
            VisualizationCategory.TOPOLOGY_GRAPH: "系统关系与架构拓扑",
            VisualizationCategory.DATA_DASHBOARD: "动态数据监控看板",
            VisualizationCategory.NONE: "数据图解",
        }
        return f"{lead} - {category_map.get(category, '可视化分析')}"
