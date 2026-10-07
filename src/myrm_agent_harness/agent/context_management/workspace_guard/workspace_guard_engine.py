"""显式工作区探索守卫与自主扫盘抑制核心引擎。

[INPUT]
- workspace_guard_types.py: 契约模型 (WorkspaceAccessPolicy, ExplorationDecisionStatus, ExplorationGuardDecision, WorkspaceGuardConfig)
- 工具调用元数据 (tool_name, tool_args)、用户提示词与会话级策略

[OUTPUT]
- PromptCrawlSuppressionFilter: 提示词对抗性扫盘意图探测与显式路径提取
- WorkspaceExplorationGuardEngine: 工具级工作区探索准入裁决与多级策略管控中枢

[POS]
- 位于 context_management/workspace_guard/workspace_guard_engine.py
"""

import os
import re

from .workspace_guard_types import (
    ExplorationDecisionStatus,
    ExplorationGuardDecision,
    WorkspaceAccessPolicy,
    WorkspaceGuardConfig,
)


class PromptCrawlSuppressionFilter:
    """提示词对抗性扫盘意图探测与显式路径提取器。"""

    @staticmethod
    def detect_crawl_suppression_intent(
        user_prompt: str,
        suppression_keywords: tuple[str, ...],
    ) -> bool:
        """检查用户提示词中是否包含明确的扫盘/翻看文件夹否定意图。"""
        if not user_prompt:
            return False
        normalized = user_prompt.lower()
        return any(kw.lower() in normalized for kw in suppression_keywords)

    @staticmethod
    def is_path_explicitly_mentioned(target_path: str, user_prompt: str) -> bool:
        """检查目标路径是否在用户输入中被显式引用或指名。"""
        if not target_path or not user_prompt:
            return False

        norm_prompt = user_prompt.strip()
        norm_target = target_path.strip()

        # 1. 直接全路径匹配
        if norm_target in norm_prompt:
            return True

        # 2. 纯文件名或基名被显式引用
        basename = os.path.basename(norm_target.rstrip("/"))
        if basename and (f"@{basename}" in norm_prompt or basename in norm_prompt):
            return True

        # 3. 相对路径形式匹配
        clean_rel = norm_target.lstrip("./")
        if clean_rel and clean_rel in norm_prompt:
            return True

        return False


class WorkspaceExplorationGuardEngine:
    """显式工作区探索守卫与自主扫盘抑制引擎。"""

    def __init__(self, config: WorkspaceGuardConfig | None = None) -> None:
        self._config = config or WorkspaceGuardConfig()
        self._filter = PromptCrawlSuppressionFilter()

    @property
    def config(self) -> WorkspaceGuardConfig:
        return self._config

    def resolve_effective_policy(
        self,
        user_prompt: str,
        session_policy: WorkspaceAccessPolicy,
    ) -> tuple[WorkspaceAccessPolicy, bool]:
        """计算当前交互轮次的最终生效策略。

        当用户提示词中显式表达了“不要翻看文件夹/仅回答理论”等否定意图时，
        该轮次将无条件对抗性升级为 EXPLICIT_ONLY 强制静默策略。

        Returns:
            tuple[生效策略, 是否由提示词对抗性触发]
        """
        suppression_triggered = self._filter.detect_crawl_suppression_intent(
            user_prompt=user_prompt,
            suppression_keywords=self._config.crawl_suppression_keywords,
        )

        if suppression_triggered:
            return WorkspaceAccessPolicy.EXPLICIT_ONLY, True

        return session_policy, False

    def evaluate_tool_exploration(
        self,
        tool_name: str,
        tool_args: dict[str, str | int | bool],
        user_prompt: str,
        session_policy: WorkspaceAccessPolicy | None = None,
    ) -> ExplorationGuardDecision:
        """评估大模型拟调用的工具是否属于探索类工具，并执行准入硬门禁。

        Args:
            tool_name: 工具名称。
            tool_args: 工具调用参数映射。
            user_prompt: 用户输入的当前轮次提示词。
            session_policy: 会话级预设策略（缺省使用全局默认值）。

        Returns:
            ExplorationGuardDecision: 详尽的准入裁决与中文反馈建议。
        """
        policy_base = session_policy or self._config.default_policy
        effective_policy, triggered = self.resolve_effective_policy(user_prompt, policy_base)

        target_path = str(
            tool_args.get("path")
            or tool_args.get("directory")
            or tool_args.get("target_dir")
            or tool_args.get("AbsolutePath")
            or ""
        )

        # 1. 非目录探索类工具直接放行
        if tool_name not in self._config.exploration_tool_names:
            return ExplorationGuardDecision(
                status=ExplorationDecisionStatus.ALLOWED,
                allowed=True,
                effective_policy=effective_policy,
                tool_name=tool_name,
                target_path=target_path,
                reason="非工作区目录探索类工具，正常放行。",
                feedback_message="",
                suppression_triggered_by_prompt=triggered,
            )

        # 2. 模式 A: EXPLICIT_ONLY (显式绝对静默模式)
        if effective_policy == WorkspaceAccessPolicy.EXPLICIT_ONLY:
            is_explicit = self._filter.is_path_explicitly_mentioned(target_path, user_prompt)
            if not is_explicit:
                status = (
                    ExplorationDecisionStatus.REJECTED_BY_PROMPT_SUPPRESSION
                    if triggered
                    else ExplorationDecisionStatus.REJECTED_BY_EXPLICIT_RULE
                )
                reason = (
                    "检测到用户提示词中包含否定性扫盘指令，已激活强制静默拦截。"
                    if triggered
                    else "当前处于 Explicit-Only 模式，用户未显式提及该路径，严禁 Agent 自主探盘。"
                )
                feedback = (
                    f"【工作区访问已拦截】用户未显式授权扫描目标目录 `{target_path or 'root'}`"
                    f"{'（提示词已明确要求不要检查文件夹）' if triggered else ''}。"
                    "请直接基于理论常识与现有会话内容回答，无需查看本地文件。"
                )
                return ExplorationGuardDecision(
                    status=status,
                    allowed=False,
                    effective_policy=effective_policy,
                    tool_name=tool_name,
                    target_path=target_path,
                    reason=reason,
                    feedback_message=feedback,
                    suppression_triggered_by_prompt=triggered,
                )

            # 显式提及则放行
            return ExplorationGuardDecision(
                status=ExplorationDecisionStatus.ALLOWED,
                allowed=True,
                effective_policy=effective_policy,
                tool_name=tool_name,
                target_path=target_path,
                reason="目标路径在用户提示词中显式声明，放行单次读取。",
                feedback_message="",
                suppression_triggered_by_prompt=triggered,
            )

        # 3. 模式 B: ON_DEMAND (按需精准单层模式)
        if effective_policy == WorkspaceAccessPolicy.ON_DEMAND:
            depth_raw = tool_args.get("depth", 1)
            depth_val = int(depth_raw) if isinstance(depth_raw, (int, str)) and str(depth_raw).isdigit() else 1

            if depth_val > self._config.max_on_demand_depth:
                return ExplorationGuardDecision(
                    status=ExplorationDecisionStatus.REJECTED_DEPTH_EXCEEDED,
                    allowed=False,
                    effective_policy=effective_policy,
                    tool_name=tool_name,
                    target_path=target_path,
                    reason=f"探测深度 {depth_val} 超过 On-Demand 最大阈值 {self._config.max_on_demand_depth}。",
                    feedback_message=(
                        f"【探测深度超限】On-Demand 模式仅允许单层浅度定位（深度 <= {self._config.max_on_demand_depth}），"
                        "禁止递归遍历大目录。请精准指定具体子目录。"
                    ),
                    suppression_triggered_by_prompt=triggered,
                )

            return ExplorationGuardDecision(
                status=ExplorationDecisionStatus.ALLOWED,
                allowed=True,
                effective_policy=effective_policy,
                tool_name=tool_name,
                target_path=target_path,
                reason="On-Demand 单层浅度目录探测符合安全准入规范。",
                feedback_message="",
                suppression_triggered_by_prompt=triggered,
            )

        # 4. 模式 C: AUTO_INDEX (全量工程索引模式)
        return ExplorationGuardDecision(
            status=ExplorationDecisionStatus.ALLOWED,
            allowed=True,
            effective_policy=effective_policy,
            tool_name=tool_name,
            target_path=target_path,
            reason="Auto-Index 工程索引模式允许全量扫描探测。",
            feedback_message="",
            suppression_triggered_by_prompt=triggered,
        )
