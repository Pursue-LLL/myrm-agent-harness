"""Information sufficiency perception, early exit gate, and high-purity context pruning.

Eliminates overthinking loops by terminating reasoning when necessary aspects are satisfied,
and prunes raw tool outputs to slash prompt time-to-first-token (TTFT).

[INPUT]
- __future__
- re
- task_graph_types

[OUTPUT]
- EarlyExitEvaluator

[POS]
Information sufficiency perception, early exit gate, and high-purity context pruning.
"""

from __future__ import annotations

import re

from .task_graph_types import (
    DAGExecutionMetrics,
    EarlyExitVerdict,
)


class EarlyExitEvaluator:
    """Evaluates information completeness to trip early exit and performs in-flight prompt pruning."""

    def __init__(
        self,
        required_aspects: tuple[str, ...] = (),
        max_iterations: int = 5,
    ) -> None:
        self.required_aspects = required_aspects
        self.max_iterations = max_iterations

    def evaluate_early_exit(
        self,
        current_iteration: int,
        gathered_aspects: set[str],
    ) -> EarlyExitVerdict:
        """Evaluate if the current reasoning loop has acquired enough information to exit early."""
        covered = tuple(sorted(a for a in self.required_aspects if a in gathered_aspects))
        missing = tuple(sorted(a for a in self.required_aspects if a not in gathered_aspects))

        # 1. Hard iteration ceiling: abort to prevent infinite overthinking loops
        if current_iteration >= self.max_iterations:
            return EarlyExitVerdict(
                should_exit=True,
                reason=f"Exceeded maximum reasoning iterations ceiling ({current_iteration} >= {self.max_iterations}).",
                covered_aspects=covered,
                missing_aspects=missing,
                iteration_count=current_iteration,
            )

        # 2. Information sufficiency: all required factual aspects have been collected
        if self.required_aspects and not missing:
            return EarlyExitVerdict(
                should_exit=True,
                reason=f"Information sufficiency satisfied: all {len(self.required_aspects)} required aspects collected.",
                covered_aspects=covered,
                missing_aspects=missing,
                iteration_count=current_iteration,
            )

        return EarlyExitVerdict(
            should_exit=False,
            reason=f"Continuing reasoning: missing required aspects ({', '.join(missing) if missing else 'none'}).",
            covered_aspects=covered,
            missing_aspects=missing,
            iteration_count=current_iteration,
        )

    @staticmethod
    def prune_context_high_purity(
        raw_text: str,
        focus_keywords: tuple[str, ...] = (),
        max_chars: int = 400,
    ) -> str:
        """Strip HTML markup, collapse excessive whitespace, and extract keyword-centric context windows."""
        # 1. Strip HTML tags
        cleaned = re.sub(r"<[^>]+>", " ", raw_text)
        # 2. Collapse repetitive whitespace
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        if len(cleaned) <= max_chars:
            return cleaned

        # 3. Locate keyword focus window if keywords specified
        if focus_keywords:
            for kw in focus_keywords:
                match = re.search(re.escape(kw), cleaned, re.IGNORECASE)
                if match:
                    start_idx = max(0, match.start() - 100)
                    end_idx = min(len(cleaned), start_idx + max_chars)
                    snippet = cleaned[start_idx:end_idx]
                    prefix = "..." if start_idx > 0 else ""
                    suffix = "..." if end_idx < len(cleaned) else ""
                    return f"{prefix}{snippet}{suffix}"

        # Default: truncate to max_chars with ellipsis
        return cleaned[:max_chars] + "..."

    @staticmethod
    def render_optimization_markdown(
        metrics: DAGExecutionMetrics,
        verdict: EarlyExitVerdict | None = None,
    ) -> str:
        """Render a GitHub Flavored Markdown card displaying DAG parallel compression and early exit stats."""
        lines: list[str] = [
            "### ⚡ 任务图关键路径裁切与早停自收敛看板",
            f"- **已执行总任务数**: `{metrics.total_tasks_executed}`",
            f"- **拓扑并发波次数**: `{metrics.total_waves}`",
            f"- **实际物理并发耗时**: `{metrics.parallel_duration_s}s`",
            f"- **若传统串行耗时**: `{metrics.simulated_serial_duration_s}s`",
            f"- **关键路径时延压缩率**: `+{metrics.latency_reduction_ratio}%`",
            "",
        ]

        if verdict:
            lines.extend(
                [
                    "#### 🎯 信息充分性与早停决策",
                    f"- **当前轮次**: `{verdict.iteration_count}`",
                    f"- **早停决议**: `{'🛑 触发早停退出' if verdict.should_exit else '🔄 继续收集信息'}`",
                    f"- **裁决原因**: {verdict.reason}",
                    f"- **已覆盖维度**: `{', '.join(verdict.covered_aspects) if verdict.covered_aspects else '无'}`",
                    "",
                ]
            )
            if verdict.should_exit:
                lines.extend(
                    [
                        "> [!NOTE]",
                        "> **[时延优化达成]** 核心事实已完全闭环，早停门禁切断了后续过度反思循环，有效降低 P95 响应耗时与 Token 消耗。",
                    ]
                )
            else:
                lines.extend(
                    [
                        "> [!TIP]",
                        "> 智能体仍在持续收敛所需事实维度，当前波次并发保持最大吞吐。",
                    ]
                )
        else:
            lines.extend(
                [
                    "> [!TIP]",
                    "> 任务图已将独立工具自动折叠并入同一波次，物理并发削减关键路径总长。",
                ]
            )

        return "\n".join(lines)
