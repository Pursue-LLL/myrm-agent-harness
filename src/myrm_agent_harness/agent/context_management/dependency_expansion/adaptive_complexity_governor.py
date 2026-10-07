# [POS] myrm_agent_harness/agent/context_management/dependency_expansion/adaptive_complexity_governor.py
# [INPUT] TaskComplexityTrack, ComplexityClassification
# [OUTPUT] AdaptiveComplexityGovernor

"""任务复杂度动态自适应双轨调度器，轻任务极简直通车与长周期项目全量工作台自适应分流。"""

from __future__ import annotations

import re

from .types import ComplexityClassification, TaskComplexityTrack

_COMPLEX_TRIGGER_PATTERNS: tuple[str, ...] = (
    r"refactor",
    r"architecture",
    r"redesign",
    r"migrate",
    r"cross-module",
    r"重构",
    r"架构",
    r"迁移",
    r"级联",
    r"跨模块",
    r"全链路",
    r"跨栈",
    r"数据模型",
    r"接口改造",
)

_LIGHTWEIGHT_TRIGGER_PATTERNS: tuple[str, ...] = (
    r"typo",
    r"button",
    r"color",
    r"script",
    r"quick",
    r"单文件",
    r"拼写",
    r"临时脚本",
    r"改按钮",
    r"注释",
    r"样式微调",
)


class AdaptiveComplexityGovernor:
    """任务复杂度动态感知双轨调度器。

    根除长程复杂工程中轻量小任务被重型 Workbench 绑架导致过度工程化与时延拖累的痛点。
    - Fast-Lean: 单文件微调、临时脚本执行，跳过重型账本写盘，0.1s 极速响应；
    - Full-Workbench: 跨栈改动、架构演进与里程碑建设，激活依赖图谱展开与状态闭环。
    """

    def __init__(self, multi_component_threshold: int = 2) -> None:
        self._multi_comp_threshold = multi_component_threshold

    def classify_task_complexity(
        self,
        task_prompt: str,
        target_components_or_files: list[str] | None = None,
        is_multi_turn_project_session: bool = False,
    ) -> ComplexityClassification:
        """评估任务复杂度并判定调度轨道。"""
        components = target_components_or_files or []
        prompt_lower = task_prompt.lower()

        # 1. 显式处于多回合长程项目会话中
        if is_multi_turn_project_session:
            return ComplexityClassification(
                track=TaskComplexityTrack.FULL_WORKBENCH,
                reason="Active multi-turn long-term project session requires full state tracking.",
                estimated_token_overhead=1200,
                bypass_state_sync=False,
            )

        # 2. 涉及多组件跨栈改动 (超出阈值)
        if len(components) >= self._multi_comp_threshold:
            return ComplexityClassification(
                track=TaskComplexityTrack.FULL_WORKBENCH,
                reason=f"Task spans multiple components ({len(components)} >= {self._multi_comp_threshold}).",
                estimated_token_overhead=1000,
                bypass_state_sync=False,
            )

        # 3. 意图特征命中复杂重构与架构改造关键词
        for pattern in _COMPLEX_TRIGGER_PATTERNS:
            if re.search(pattern, prompt_lower):
                return ComplexityClassification(
                    track=TaskComplexityTrack.FULL_WORKBENCH,
                    reason=f"Prompt matches complex architectural pattern '{pattern}'.",
                    estimated_token_overhead=1500,
                    bypass_state_sync=False,
                )

        # 4. 显式命中轻量任务模式
        for pattern in _LIGHTWEIGHT_TRIGGER_PATTERNS:
            if re.search(pattern, prompt_lower):
                return ComplexityClassification(
                    track=TaskComplexityTrack.FAST_LEAN,
                    reason=f"Prompt matches lightweight single-turn pattern '{pattern}'.",
                    estimated_token_overhead=0,
                    bypass_state_sync=True,
                )

        # 5. 默认策略：若组件数 <= 1 且无复杂关键词，走轻量通道避免过度工程
        if len(components) <= 1:
            return ComplexityClassification(
                track=TaskComplexityTrack.FAST_LEAN,
                reason="Default lightweight track: single component task without complex triggers.",
                estimated_token_overhead=0,
                bypass_state_sync=True,
            )

        return ComplexityClassification(
            track=TaskComplexityTrack.FULL_WORKBENCH,
            reason="Fallback to full workbench for safe dependency governance.",
            estimated_token_overhead=800,
            bypass_state_sync=False,
        )
