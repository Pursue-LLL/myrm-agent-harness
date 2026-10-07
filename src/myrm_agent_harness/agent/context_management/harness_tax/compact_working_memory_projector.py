"""极紧凑 Working Memory 投影器、显式 Resource Loader 与超低 Harness Tax 控制引擎。

实现 Pi Agent Pareto 前沿极简工程心法：最小工具集暴露、显式资源装配与工作记忆紧凑投影。

[INPUT]
- available_tools: Sequence[ToolDescriptor]
- raw_messages: Sequence[BaseMessage]
- config: HarnessTaxConfig

[OUTPUT]
- CompactWorkingMemoryProjector: 核心投影与治理引擎

[POS]
- 位于 context_management/harness_tax/compact_working_memory_projector.py
"""

from collections.abc import Sequence
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from myrm_agent_harness.utils.token_estimation import estimate_context_tokens

from .harness_tax_types import (
    CompactWorkingMemoryView,
    HarnessTaxAuditReport,
    HarnessTaxConfig,
    ResourceLoadBundle,
    ToolDescriptor,
    ToolExposurePolicy,
)


class CompactWorkingMemoryProjector:
    """超低 Harness Tax 控制器与 Working Memory 投影引擎。"""

    def __init__(self, config: HarnessTaxConfig | None = None) -> None:
        self.config = config or HarnessTaxConfig()

    def compile_resource_bundle(
        self,
        profile_id: str,
        enabled_skills: Sequence[str],
        custom_instructions: str = "",
        prompt_template: str = "",
    ) -> ResourceLoadBundle:
        """运行前显式预编译装配当前 Profile 的最小资源包，杜绝全量规则动态倾倒。"""
        skill_manifests: list[str] = [f"- skill: {s.strip()}" for s in enabled_skills if s.strip()]
        skill_summary = "\n".join(skill_manifests) if skill_manifests else "None"

        combined_system = (
            f"Profile: {profile_id}\n"
            f"Active Skills:\n{skill_summary}\n"
            f"Instructions:\n{custom_instructions.strip()}"
        )
        loaded_tokens = max(1, len(combined_system) // 4)

        return ResourceLoadBundle(
            profile_id=profile_id,
            system_instructions=combined_system,
            active_skill_names=list(enabled_skills),
            prompt_template=prompt_template,
            loaded_tokens=loaded_tokens,
        )

    def filter_active_tools(
        self,
        available_tools: Sequence[ToolDescriptor],
        current_phase: str | None = None,
    ) -> list[ToolDescriptor]:
        """依据策略动态收缩暴露给模型的工具集合，大幅削减工具 Schema 的 Harness Tax。"""
        if self.config.exposure_policy == ToolExposurePolicy.FULL_CAPABILITY:
            return list(available_tools)

        whitelist = set(self.config.core_tool_whitelist)
        core_tools: list[ToolDescriptor] = []
        secondary_tools: list[ToolDescriptor] = []

        for tool in available_tools:
            if tool.name in whitelist or tool.is_core:
                core_tools.append(tool)
            else:
                secondary_tools.append(tool)

        # 策略 1: 最小核心集合 (Pareto 4 工具)
        if self.config.exposure_policy == ToolExposurePolicy.MINIMAL_CORE_ONLY:
            combined = core_tools + secondary_tools
            return combined[: self.config.max_active_tools]

        # 策略 2: 意图感知动态挂载
        if self.config.exposure_policy == ToolExposurePolicy.INTENT_ADAPTIVE:
            phase_key = (current_phase or "general").lower()
            matched_secondary = [t for t in secondary_tools if t.category.lower() == phase_key]
            combined = core_tools + matched_secondary
            return combined[: max(self.config.max_active_tools, len(core_tools) + 2)]

        return list(available_tools)

    def project_working_memory(
        self,
        session_id: str,
        raw_messages: Sequence[BaseMessage],
        current_goal: str | None = None,
    ) -> CompactWorkingMemoryView:
        """将底层完整历史投影为极紧凑的当前 Working Memory 视图。"""
        msg_list: list[BaseMessage] = list(raw_messages)
        original_tokens = estimate_context_tokens(msg_list)

        if not self.config.enable_active_branch_projection or len(msg_list) <= self.config.recent_turns_retention * 2:
            # 消息量少时直接附带 Goal 返回
            projected = self._inject_goal_node(msg_list, current_goal)
            projected_tokens = estimate_context_tokens(projected)
            return CompactWorkingMemoryView(
                session_id=session_id,
                projected_messages=projected,
                original_tokens=original_tokens,
                projected_tokens=projected_tokens,
                harness_tax_saved_tokens=max(0, original_tokens - projected_tokens),
                reduction_ratio=round(max(0, original_tokens - projected_tokens) / max(1, original_tokens), 4),
            )

        # 划分历史与最近活跃窗口
        protect_count = self.config.recent_turns_retention * 2
        older_messages = msg_list[:-protect_count]
        recent_messages = msg_list[-protect_count:]

        preserved_prefix: list[BaseMessage] = []
        to_collapse: list[BaseMessage] = []

        for m in older_messages:
            if isinstance(m, SystemMessage) and not to_collapse:
                preserved_prefix.append(m)
            else:
                to_collapse.append(m)

        # 提取历史关键里程碑与决策，折叠冗余闲聊
        milestones: list[str] = []
        for m in to_collapse:
            if isinstance(m, HumanMessage):
                milestones.append(f"User Goal: {str(m.content)[:60]}")
            elif isinstance(m, AIMessage) and ("plan" in str(m.content).lower() or "completed" in str(m.content).lower()):
                milestones.append(f"AI Plan: {str(m.content)[:60]}")

        summary_block = (
            "[Compact Working Memory Projection]\n"
            f"Collapsed turns: {len(to_collapse)}\n"
            "Key Active Milestones:\n"
            + ("\n".join(f"- {s}" for s in milestones[:4]) if milestones else "- Previous execution on track")
        )
        milestone_node = SystemMessage(content=summary_block)

        projected = [*preserved_prefix, milestone_node, *recent_messages]
        projected = self._inject_goal_node(projected, current_goal)
        projected_tokens = estimate_context_tokens(projected)
        saved = max(0, original_tokens - projected_tokens)

        return CompactWorkingMemoryView(
            session_id=session_id,
            projected_messages=projected,
            original_tokens=original_tokens,
            projected_tokens=projected_tokens,
            harness_tax_saved_tokens=saved,
            reduction_ratio=round(saved / max(1, original_tokens), 4),
        )

    def audit_harness_tax(
        self,
        raw_tools: Sequence[ToolDescriptor],
        projected_tools: Sequence[ToolDescriptor],
        original_context_tokens: int,
        projected_context_tokens: int,
    ) -> HarnessTaxAuditReport:
        """评估计算因工具收缩与工作记忆投影所节约的框架税 (Harness Tax)。"""
        base_tool_tokens = sum(t.schema_tokens_estimate for t in raw_tools)
        proj_tool_tokens = sum(t.schema_tokens_estimate for t in projected_tools)
        tool_saved = max(0, base_tool_tokens - proj_tool_tokens)
        context_saved = max(0, original_context_tokens - projected_context_tokens)
        total_saved = tool_saved + context_saved

        total_base = base_tool_tokens + original_context_tokens
        savings_pct = round((total_saved / total_base) * 100.0, 2) if total_base > 0 else 0.0

        return HarnessTaxAuditReport(
            base_tool_schema_tokens=base_tool_tokens,
            projected_tool_schema_tokens=proj_tool_tokens,
            tool_tokens_saved=tool_saved,
            context_tokens_saved=context_saved,
            total_tokens_saved=total_saved,
            estimated_cost_savings_pct=savings_pct,
        )

    def _inject_goal_node(
        self,
        messages: list[BaseMessage],
        current_goal: str | None,
    ) -> list[BaseMessage]:
        """将当前活跃目标显式固定注入至顶部作为指导锚点。"""
        if not current_goal:
            return messages
        goal_msg = SystemMessage(content=f"[Current Active Goal Milestone]: {current_goal.strip()}")
        # 插入在已有系统提示后或第一位
        if messages and isinstance(messages[0], SystemMessage):
            return [messages[0], goal_msg, *messages[1:]]
        return [goal_msg, *messages]
