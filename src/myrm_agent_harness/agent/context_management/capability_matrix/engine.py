"""[INPUT]
- models: CapabilityHintChip, CommandCategory, CommandMatrixEntry, ContextStateSnapshot

[OUTPUT]
- CapabilityDiscoveryEngine: Context-aware heuristic engine evaluating runtime state and yielding hint chips

[POS]
Harness framework layer engine for progressive capability discovery and interactive command hints (Item 38 P0).
"""

from __future__ import annotations

from .models import (
    CapabilityHintChip,
    ContextStateSnapshot,
)


class CapabilityDiscoveryEngine:
    """Heuristic engine recommending high-leverage commands based on session lifecycle state."""

    @classmethod
    def evaluate_recommendations(
        cls,
        context: ContextStateSnapshot,
        max_results: int = 3,
    ) -> list[CapabilityHintChip]:
        chips: list[CapabilityHintChip] = []
        mastered = set(context.mastered_commands)

        # Heuristic 1: Long-running task in-flight -> Suggest concurrent background / btw barge-in
        if context.status == "running":
            if "/btw" not in mastered:
                chips.append(
                    CapabilityHintChip(
                        chip_id="hint_btw",
                        command="/btw",
                        label_zh="临时插话 /btw",
                        label_en="Barge-in /btw",
                        reason_zh="任务正在执行？输入 /btw 可快速提问且不打断当前主执行流",
                        reason_en="Task in progress? Use /btw for a side question without stopping the agent",
                        priority=100,
                        insert_prompt="/btw ",
                    )
                )

            if "/bg" not in mastered and context.running_step_count >= 2:
                chips.append(
                    CapabilityHintChip(
                        chip_id="hint_bg",
                        command="/bg",
                        label_zh="转入后台 /bg",
                        label_en="Move to Background /bg",
                        reason_zh="耗时任务处理中？输入 /bg 可将其转为后台独立异步任务",
                        reason_en="Long job? Use /bg to fork into an independent background runner",
                        priority=90,
                        insert_prompt="/bg",
                    )
                )

            if "/steer" not in mastered:
                chips.append(
                    CapabilityHintChip(
                        chip_id="hint_steer",
                        command="/steer",
                        label_zh="实时纠偏 /steer",
                        label_en="Steer Agent /steer",
                        reason_zh="执行方向需要调整？输入 /steer 给智能体补充关键约束",
                        reason_en="Need course correction? Use /steer to guide the execution path",
                        priority=80,
                        insert_prompt="/steer ",
                    )
                )

        # Heuristic 2: Data analysis or coding tools active -> Suggest persistent REPL
        has_code_tools = any(
            t in ("bash", "python", "pykernel", "sql", "code_execution")
            for t in context.recent_tools
        )
        if has_code_tools and "/pykernel" not in mastered:
            chips.append(
                CapabilityHintChip(
                    chip_id="hint_pykernel",
                    command="/pykernel",
                    label_zh="持久内核 /pykernel",
                    label_en="Persistent REPL /pykernel",
                    reason_zh="正在进行数据或代码操作？开启 /pykernel 保活 DataFrame 与变量内存",
                    reason_en="Working with code? Use /pykernel to keep variables and DataFrames in memory",
                    priority=85,
                    insert_prompt="/pykernel start",
                )
            )

        # Heuristic 3: Complex multi-step task completed -> Suggest solidify SOP or export
        if context.status == "idle" and context.running_step_count >= 3:
            if "/sop" not in mastered:
                chips.append(
                    CapabilityHintChip(
                        chip_id="hint_sop",
                        command="/sop",
                        label_zh="固化 SOP /sop",
                        label_en="Solidify SOP /sop",
                        reason_zh="本次复杂任务执行效果很好？输入 /sop 一键提炼为团队可复用工作流",
                        reason_en="Workflow succeeded? Use /sop to distill into a reusable workflow recipe",
                        priority=75,
                        insert_prompt="/sop create",
                    )
                )
            if "/export" not in mastered:
                chips.append(
                    CapabilityHintChip(
                        chip_id="hint_export",
                        command="/export",
                        label_zh="打包导出 /export",
                        label_en="Export Pack /export",
                        reason_zh="需要留档或分享成果？输入 /export 生成自包含产物清单",
                        reason_en="Need archival? Use /export to package deliverables and execution traces",
                        priority=70,
                        insert_prompt="/export zip",
                    )
                )

        # Sort by priority descending and slice
        chips.sort(key=lambda c: c.priority, reverse=True)
        return chips[:max_results]
