"""单元测试：百万 Token 超大上下文动态自适应压实与双轨绝对上限守卫套件。

[INPUT]
- MillionTokenCeilingGovernor, MillionTokenCeilingConfig, CompactionTierAction

[OUTPUT]
- 验证双轨计算、防饥饿判定、Tier 1 工具外部化落盘与回溯、Tier 2 增量摘要。

[POS]
- 位于 tests/agent/context_management/test_million_token_ceiling_governor.py
"""

from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
import pytest

from myrm_agent_harness.agent.context_management.million_token_ceiling import (
    CompactionTierAction,
    MillionTokenCeilingConfig,
    MillionTokenCeilingGovernor,
)


def test_dual_track_budget_and_starvation_prevention() -> None:
    """验证百万模型下避免传统比例推高导致的压缩饥饿 (Compaction Starvation)。"""
    config = MillionTokenCeilingConfig(
        physical_context_limit=1_050_000,
        ratio_threshold=0.75,
        operational_soft_ceiling=64_000,
        operational_hard_ceiling=96_000,
    )
    governor = MillionTokenCeilingGovernor(config=config)

    # 传统按比例阈值会高达 787,500
    assert config.naive_ratio_threshold == 787_500
    # 动态自适应软上限钳制在 64,000
    assert config.effective_compress_threshold == 64_000
    assert config.effective_hard_ceiling == 96_000

    # 当当前会话累积至 70,000 Tokens 时
    forecast = governor.calculate_forecast(current_tokens=70_000)
    assert forecast.compaction_starvation_prevented is True
    assert forecast.projected_ttft_ms > 0
    assert forecast.projected_turn_cost_usd > 0

    # 判定动作应进入 Tier 1 工具外部化
    action = governor.determine_tier_action(70_000)
    assert action == CompactionTierAction.TIER1_OFFLOAD_TOOLS

    # 若当前仅 30,000 Tokens，低于软上限，不触发压缩且未陷入饥饿
    low_forecast = governor.calculate_forecast(current_tokens=30_000)
    assert low_forecast.compaction_starvation_prevented is False
    assert governor.determine_tier_action(30_000) == CompactionTierAction.NONE


def test_tier1_tool_offloading_and_rehydration(tmp_path: Path) -> None:
    """验证 Tier 1 工具输出无损外部化落盘、引用卡片替换与无损还原。"""
    config = MillionTokenCeilingConfig(
        physical_context_limit=1_000_000,
        operational_soft_ceiling=100,  # 设定极小测试门槛快速触发
        operational_hard_ceiling=5000,
        min_tool_offload_tokens=50,
        protected_recent_turns=1,
    )
    governor = MillionTokenCeilingGovernor(config=config, default_storage_dir=tmp_path)

    large_tool_payload = "LONG_LOG_DATA_STDOUT " * 100  # 约 500 tokens
    messages = [
        SystemMessage(content="You are an expert AI."),
        HumanMessage(content="Run build command."),
        AIMessage(content="Running tool..."),
        ToolMessage(content=large_tool_payload, tool_call_id="call_bash_001", name="bash"),
        # 最新一轮（受保护）
        HumanMessage(content="What is the result?"),
        AIMessage(content="Checking result..."),
        ToolMessage(content="Success summary", tool_call_id="call_recent_002", name="bash"),
    ]

    result = governor.execute_compaction(messages=messages, storage_dir=tmp_path)

    assert result.is_compacted is True
    assert result.tier_action == CompactionTierAction.TIER1_OFFLOAD_TOOLS
    assert result.after_tokens < result.before_tokens
    assert len(result.offloaded_artifacts) == 1

    artifact = result.offloaded_artifacts[0]
    assert artifact.tool_call_id == "call_bash_001"
    assert "ref://context/tools/call_bash_001" in artifact.ref_handle
    assert Path(artifact.disk_path).exists()

    # 验证替换后的 ToolMessage 包含了引用信息
    compacted_tool_msg = result.messages[3]
    assert isinstance(compacted_tool_msg, ToolMessage)
    assert "Tool Output Offloaded to Storage" in str(compacted_tool_msg.content)
    assert "ref://context/tools/call_bash_001" in str(compacted_tool_msg.content)

    # 验证保护区内的最近 ToolMessage 未被替换
    recent_tool_msg = result.messages[6]
    assert str(recent_tool_msg.content) == "Success summary"

    # 验证从磁盘无损还原
    restored_raw = governor.restore_offloaded_tool(artifact.disk_path)
    assert restored_raw == large_tool_payload


def test_tier2_rolling_summary_on_hard_ceiling(tmp_path: Path) -> None:
    """验证超过有效硬上限时触发 Tier 2 增量滚动摘要。"""
    config = MillionTokenCeilingConfig(
        physical_context_limit=1_000_000,
        operational_soft_ceiling=100,
        operational_hard_ceiling=200,
        min_tool_offload_tokens=50,
        protected_recent_turns=1,
    )
    governor = MillionTokenCeilingGovernor(config=config, default_storage_dir=tmp_path)

    long_dialogue_chunk = "Detailed previous discussion about architectural requirements and constraints. " * 10
    messages = [
        SystemMessage(content="System instruction base"),
        HumanMessage(content=f"Old query 1: {long_dialogue_chunk}"),
        AIMessage(content=f"Old answer 1: {long_dialogue_chunk}"),
        HumanMessage(content=f"Old query 2: {long_dialogue_chunk}"),
        AIMessage(content=f"Old answer 2: {long_dialogue_chunk}"),
        # 最新一轮受保护
        HumanMessage(content="Latest user request"),
        AIMessage(content="Latest assistant plan"),
    ]

    result = governor.execute_compaction(messages=messages, storage_dir=tmp_path)

    assert result.is_compacted is True
    assert result.tier_action == CompactionTierAction.TIER2_ROLLING_SUMMARY
    # 历史多轮应被折叠为一个滚动摘要节点
    summary_messages = [m for m in result.messages if "Historical Turns Rolling Compacted" in str(m.content)]
    assert len(summary_messages) == 1
    # 最新的两轮消息完好保留
    assert result.messages[-2].content == "Latest user request"
    assert result.messages[-1].content == "Latest assistant plan"


def test_pass_through_when_below_ceiling() -> None:
    """验证当 Token 水位未越界时直接透传，无任何损耗。"""
    config = MillionTokenCeilingConfig(
        physical_context_limit=1_000_000,
        operational_soft_ceiling=10_000,
        operational_hard_ceiling=20_000,
    )
    governor = MillionTokenCeilingGovernor(config=config)

    messages = [
        SystemMessage(content="System"),
        HumanMessage(content="Hello"),
        AIMessage(content="Hi there"),
    ]

    result = governor.execute_compaction(messages=messages)
    assert result.is_compacted is False
    assert result.tier_action == CompactionTierAction.NONE
    assert len(result.messages) == 3
    assert result.before_tokens == result.after_tokens
