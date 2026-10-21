"""Roundtrip budget governance gate and efficiency auditor.

Enforces the hard benchmark established by huashu-mac-use:
Model roundtrips per valid screenshot or atomic action must be <= 2
(compressing roundtrips by over 75% compared to naive exploratory prompt loops).

[INPUT]
- __future__
- time
- code_over_prompt_types

[OUTPUT]
- RoundtripBudgetGate

[POS]
Roundtrip budget governance gate and efficiency auditor.
"""

from __future__ import annotations

import time

from .code_over_prompt_types import RoundtripBudgetVerdict


class RoundtripBudgetGate:
    """Audits conversational roundtrips per task and trips alerts when budgets are exceeded."""

    def __init__(self, task_name: str, max_budget: int = 2) -> None:
        self.task_name = task_name
        self.max_budget = max_budget
        self._action_counts: dict[str, int] = {}
        self._total_roundtrips = 0
        self._start_time = time.time()

    def record_turn(self, action_name: str, count: int = 1) -> int:
        """Increment roundtrip count for a specific action category."""
        self._action_counts[action_name] = self._action_counts.get(action_name, 0) + count
        self._total_roundtrips += count
        return self._total_roundtrips

    def evaluate(self) -> RoundtripBudgetVerdict:
        """Evaluate whether current execution satisfies the roundtrip compression metric."""
        exceeded = max(0, self._total_roundtrips - self.max_budget)
        passed = self._total_roundtrips <= self.max_budget

        # Baseline comparison: naive prompt loop averaged 8 roundtrips
        baseline_cost = 8.0
        efficiency_ratio = round(
            (baseline_cost - self._total_roundtrips) / baseline_cost * 100.0, 1
        ) if self._total_roundtrips < baseline_cost else 0.0

        return RoundtripBudgetVerdict(
            passed=passed,
            current_roundtrips=self._total_roundtrips,
            max_budget=self.max_budget,
            exceeded_by=exceeded,
            efficiency_ratio=efficiency_ratio,
        )

    def render_markdown_card(self) -> str:
        """Render a GitHub Flavored Markdown card showing roundtrip metrics and compression ratio."""
        verdict = self.evaluate()
        elapsed_s = round(time.time() - self._start_time, 2)

        lines: list[str] = [
            f"### 🎯 经验代码化往返压缩审计卡片: `{self.task_name}`",
            f"- **当前模型交互往返**: `{verdict.current_roundtrips}` 次",
            f"- **硬性预算门禁上限**: `≤ {verdict.max_budget}` 次",
            f"- **相较未经重构基线(8次)效率提升**: `+{verdict.efficiency_ratio}%`",
            f"- **总耗时**: `{elapsed_s}s`",
            "",
            "#### 🔍 动作交互分布",
        ]

        if self._action_counts:
            for act, cnt in self._action_counts.items():
                lines.append(f"- **`{act}`**: {cnt} 次往返")
        else:
            lines.append("- *(无交互记录)*")

        lines.append("")
        if verdict.passed:
            lines.extend(
                [
                    "> [!NOTE]",
                    f"> **[指标达成]** 单任务交互往返严格控制在 {verdict.current_roundtrips}/{verdict.max_budget} 次以内，经验代码化下沉达标。",
                ]
            )
        else:
            lines.extend(
                [
                    "> [!WARNING]",
                    f"> **[预算超标]** 当前任务交互往返达 {verdict.current_roundtrips} 次（超标 {verdict.exceeded_by} 次）。建议检查是否将低级试探下沉为确定性代码。",
                ]
            )

        return "\n".join(lines)
