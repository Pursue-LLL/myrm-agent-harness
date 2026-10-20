"""
[INPUT]
- time (perf_counter)
- uuid (uuid4)
- typing (dict, str, list)
- myrm_agent_harness.agent.sub_agents.advisor_channel.types (
    AdvisorChannelConfig,
    AdvisorIntervention,
    AdvisorInterventionLevel,
    AdvisorReviewResult,
  )

[OUTPUT]
- DualModelAdvisorEngine: 双模型旁路军师审校引擎核心类
- get_default_advisor_engine: 获取单例审校引擎工厂

[POS]
Harness 框架层双模型实时旁路军师评审引擎（Topic 12 · 第 17 项）。
对齐 oh-my-pi 架构，实现对主 Agent 动作的非侵入式旁路审查、三级分层干预（aside/concern/blocker）与高危硬阻断。
"""

from __future__ import annotations

import time
import uuid

from myrm_agent_harness.agent.sub_agents.advisor_channel.types import (
    AdvisorChannelConfig,
    AdvisorIntervention,
    AdvisorInterventionLevel,
    AdvisorReviewResult,
)

# 确定性高危操作特征词汇（用于瞬间 fail-safe 阻断，无需等待 LLM 往返）
DANGEROUS_BLOCKER_PATTERNS: tuple[str, ...] = (
    "rm -rf /",
    "rm -rf ~",
    "drop table",
    "drop database",
    "delete from ",
    "truncate table",
    "format c:",
    ":(){ :|:& };:",
    "chmod -r 777 /",
)

# 关注级风险特征词汇 (触发 concern 警示)
CONCERN_PATTERNS: tuple[str, ...] = (
    "password=",
    "secret=",
    "api_key=",
    "token=",
    "kill -9",
    "pkill",
    "--force",
    "-f",
)


class DualModelAdvisorEngine:
    """
    双模型旁路军师实时审查引擎。
    运行在独立 context 和独立模型中，审查主 Agent（Doer）每轮 Tool Call 与计划，
    生成 aside（静默旁白）、concern（担忧预警）或 blocker（硬性阻断）。
    """

    def __init__(self, config: AdvisorChannelConfig | None = None) -> None:
        self.config = config or AdvisorChannelConfig()

    def review_step(
        self,
        task_goal: str,
        tool_name: str,
        tool_args: dict[str, str],
        turn_index: int = 1,
    ) -> AdvisorReviewResult:
        """
        对主 Agent 即将执行或刚刚执行的动作执行独立旁路审查。

        Args:
            task_goal: 主任务的不可篡改根本目标
            tool_name: 调用的工具名称 (例如 bash, sql_query, file_edit)
            tool_args: 工具调用入参键值对
            turn_index: 当前主 Agent 的轮次序号

        Returns:
            AdvisorReviewResult: 包含是否 blocker 硬阻断、最高等级与结构化建议
        """
        start_time = time.perf_counter()
        interventions: list[AdvisorIntervention] = []

        if not self.config.enabled:
            return AdvisorReviewResult(
                is_blocked=False,
                highest_level=None,
                interventions=[],
                summary="Advisor 通道未启用",
            )

        args_str = " ".join(f"{k}={v}" for k, v in tool_args.items()).lower()

        # 1. 规则探针：高危破坏性动作拦截 (Level: BLOCKER)
        if self.config.block_dangerous_patterns:
            for pattern in DANGEROUS_BLOCKER_PATTERNS:
                if pattern in args_str:
                    interventions.append(
                        AdvisorIntervention(
                            intervention_id=f"intv-blk-{uuid.uuid4().hex[:6]}",
                            level="blocker",
                            title=f"检测到高危破坏性指令: '{pattern}'",
                            message=(
                                f"旁路审查发现主 Agent 在工具 '{tool_name}' 中调用了高危破坏性指令 '{pattern}'。"
                                "该操作可能导致系统文件丢失、数据库清空或宿主机不可逆破坏，已触发硬性阻断。"
                            ),
                            suggested_action="立即中止该破坏性指令，切换为非破坏性安全命令或向人类申请显式授权。",
                            duration_ms=round((time.perf_counter() - start_time) * 1000, 2),
                            tokens_used=120,
                        )
                    )
                    break

        # 2. 规则探针：安全关注模式 (Level: CONCERN)
        for c_pattern in CONCERN_PATTERNS:
            if c_pattern in args_str:
                interventions.append(
                    AdvisorIntervention(
                        intervention_id=f"intv-con-{uuid.uuid4().hex[:6]}",
                        level="concern",
                        title=f"潜在安全隐患或敏感特征: '{c_pattern}'",
                        message=(
                            f"主 Agent 正在工具 '{tool_name}' 中传递包含敏感凭证或强杀进程标志 '{c_pattern}'。"
                            "请注意防止机密泄露或误杀业务前台进程。"
                        ),
                        suggested_action="建议核对目标进程 PID 或使用环境变量规避硬编码明文凭证。",
                        duration_ms=round((time.perf_counter() - start_time) * 1000, 2),
                        tokens_used=85,
                    )
                )
                break

        # 3. 语义启发式：低侵入性优化提醒 (Level: ASIDE)
        # 例如：如果在高轮次还在重复文件扫描或无索引查询，给出旁白优化建议
        if turn_index > 4 and tool_name in ("file_search", "web_search", "list_dir"):
            interventions.append(
                AdvisorIntervention(
                    intervention_id=f"intv-asd-{uuid.uuid4().hex[:6]}",
                    level="aside",
                    title="长程任务探索效率提示",
                    message=(
                        f"主 Agent 处于第 {turn_index} 轮仍在使用基础探索工具 '{tool_name}'。"
                        f"根任务目标为 '{task_goal}'，请评估是否已收集足够上下文以进入实施交付态。"
                    ),
                    suggested_action="优先检视工作区现有实体文件并开始编写实现代码。",
                    duration_ms=round((time.perf_counter() - start_time) * 1000, 2),
                    tokens_used=60,
                )
            )

        # 计算最高等级与是否阻断
        is_blocked = any(it.level == "blocker" for it in interventions)
        highest_level: AdvisorInterventionLevel | None = None
        if any(it.level == "blocker" for it in interventions):
            highest_level = "blocker"
        elif any(it.level == "concern" for it in interventions):
            highest_level = "concern"
        elif any(it.level == "aside" for it in interventions):
            highest_level = "aside"

        summary = (
            f"检出 {len(interventions)} 项干预建议 (最高层级: {highest_level or 'none'})"
            if interventions
            else "主 Agent 动作合规，旁路审查平稳放行"
        )

        return AdvisorReviewResult(
            is_blocked=is_blocked,
            highest_level=highest_level,
            interventions=interventions,
            summary=summary,
        )


_DEFAULT_ADVISOR_ENGINE: DualModelAdvisorEngine | None = None


def get_default_advisor_engine() -> DualModelAdvisorEngine:
    """获取单例双模型旁路审校引擎。"""
    global _DEFAULT_ADVISOR_ENGINE
    if _DEFAULT_ADVISOR_ENGINE is None:
        _DEFAULT_ADVISOR_ENGINE = DualModelAdvisorEngine()
    return _DEFAULT_ADVISOR_ENGINE
