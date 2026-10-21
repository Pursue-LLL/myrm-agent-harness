"""
[INPUT]
- pytest
- myrm_agent_harness.agent.sub_agents.advisor_channel (
    AdvisorChannelConfig,
    DualModelAdvisorEngine,
  )

[OUTPUT]
- test_advisor_benign_action_passed: 测试合规安全操作平稳放行
- test_advisor_dangerous_action_blocker: 测试高危破坏性指令触发 blocker 硬阻断
- test_advisor_concern_detection: 测试敏感凭证与强杀进程触发 concern 预警
- test_advisor_long_running_aside_advice: 测试长程任务高轮次触发 aside 优化提示
- test_advisor_disabled_bypass: 测试旁路通道禁用时直接放行

[POS]
Harness 框架层双模型实时旁路军师评审通道自动化测试套件（Topic 12 · 第 17 项）。
覆盖正常放行、高危 blocker 硬阻断熔断、concern 风险预警、aside 提示与旁路禁用旁路。
"""

from __future__ import annotations

from myrm_agent_harness.agent.sub_agents.advisor_channel import (
    AdvisorChannelConfig,
    DualModelAdvisorEngine,
)


def test_advisor_benign_action_passed() -> None:
    """验证主 Agent 的常规合规操作平稳放行。"""
    engine = DualModelAdvisorEngine()

    result = engine.review_step(
        task_goal="Refactor user profile component",
        tool_name="view_file",
        tool_args={"path": "src/components/UserProfile.tsx"},
        turn_index=1,
    )

    assert result.is_blocked is False
    assert result.highest_level is None
    assert len(result.interventions) == 0
    assert "平稳放行" in result.summary


def test_advisor_dangerous_action_blocker() -> None:
    """验证命中高危破坏性指令时触发 blocker 硬阻断熔断。"""
    engine = DualModelAdvisorEngine()

    # 模拟高危删除命令
    result = engine.review_step(
        task_goal="Clean up temp files",
        tool_name="bash",
        tool_args={"command": "rm -rf / --no-preserve-root"},
        turn_index=2,
    )

    assert result.is_blocked is True
    assert result.highest_level == "blocker"
    assert len(result.interventions) == 1

    intv = result.interventions[0]
    assert intv.level == "blocker"
    assert "高危破坏性指令" in intv.title
    assert "已触发硬性阻断" in intv.message
    assert intv.suggested_action is not None


def test_advisor_concern_detection() -> None:
    """验证检测到敏感特征或强杀操作时触发 concern 预警。"""
    engine = DualModelAdvisorEngine()

    result = engine.review_step(
        task_goal="Restart dev server",
        tool_name="bash",
        tool_args={"command": "kill -9 8080"},
        turn_index=3,
    )

    assert result.is_blocked is False
    assert result.highest_level == "concern"
    assert len(result.interventions) == 1

    intv = result.interventions[0]
    assert intv.level == "concern"
    assert "潜在安全隐患" in intv.title


def test_advisor_long_running_aside_advice() -> None:
    """验证高轮次依然在浅层探索时触发 aside 效率提示。"""
    engine = DualModelAdvisorEngine()

    result = engine.review_step(
        task_goal="Fix payment webhook race condition",
        tool_name="web_search",
        tool_args={"query": "stripe webhook error codes"},
        turn_index=6,
    )

    assert result.is_blocked is False
    assert result.highest_level == "aside"
    assert len(result.interventions) == 1

    intv = result.interventions[0]
    assert intv.level == "aside"
    assert "长程任务探索效率提示" in intv.title
    assert "优先检视工作区现有实体文件" in (intv.suggested_action or "")


def test_advisor_disabled_bypass() -> None:
    """验证禁用 Advisor 通道时完全跳过审查。"""
    engine = DualModelAdvisorEngine(config=AdvisorChannelConfig(enabled=False))

    result = engine.review_step(
        task_goal="Format disk",
        tool_name="bash",
        tool_args={"command": "rm -rf /"},
        turn_index=1,
    )

    assert result.is_blocked is False
    assert result.highest_level is None
    assert len(result.interventions) == 0
    assert "未启用" in result.summary
