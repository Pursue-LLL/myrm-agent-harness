"""Unit tests for VoiceCommandLocalBypassAndTieredIntentRoutingSuite.

[INPUT]
VoiceCommandLocalBypassAndTieredIntentRoutingSuite, VoiceBypassConfig, VoiceIntentTier, VoiceActionCategory.

[OUTPUT]
Unit test assertions validating Tier-0 deterministic bypass, normalization, and Tier-1 fallback.

[POS]
Test file in tests/agent/context_management/test_voice_command_bypass_suite.py.
"""

from __future__ import annotations

from myrm_agent_harness.agent.context_management import (
    VoiceActionCategory,
    VoiceBypassConfig,
    VoiceCommandLocalBypassAndTieredIntentRoutingSuite,
    VoiceIntentTier,
)


def test_tier0_execution_controls() -> None:
    """Verify high-frequency execution control commands resolve deterministically to Tier-0."""
    suite = VoiceCommandLocalBypassAndTieredIntentRoutingSuite()

    # Stop command
    res_stop = suite.route_utterance("停止")
    assert res_stop.tier == VoiceIntentTier.TIER0_LOCAL_BYPASS
    assert res_stop.is_bypass is True
    assert res_stop.action is not None
    assert res_stop.action.action_id == "stop_execution"
    assert res_stop.action.category == VoiceActionCategory.EXECUTION_CONTROL
    assert res_stop.tokens_saved > 0

    # Pause command
    res_pause = suite.route_utterance("pause")
    assert res_pause.tier == VoiceIntentTier.TIER0_LOCAL_BYPASS
    assert res_pause.action is not None
    assert res_pause.action.action_id == "pause_execution"

    # Retry command
    res_retry = suite.route_utterance("再试一次")
    assert res_retry.tier == VoiceIntentTier.TIER0_LOCAL_BYPASS
    assert res_retry.action is not None
    assert res_retry.action.action_id == "retry_turn"

    # Resume command
    res_resume = suite.route_utterance("继续运行")
    assert res_resume.tier == VoiceIntentTier.TIER0_LOCAL_BYPASS
    assert res_resume.action is not None
    assert res_resume.action.action_id == "resume_execution"


def test_tier0_navigation_and_views() -> None:
    """Verify session navigation and view commands resolve to Tier-0 actions."""
    suite = VoiceCommandLocalBypassAndTieredIntentRoutingSuite()

    # New session
    res_new = suite.route_utterance("新建会话")
    assert res_new.tier == VoiceIntentTier.TIER0_LOCAL_BYPASS
    assert res_new.action is not None
    assert res_new.action.action_id == "new_session"
    assert res_new.action.category == VoiceActionCategory.SESSION_NAVIGATE

    # Clear chat
    res_clear = suite.route_utterance("clear chat")
    assert res_clear.tier == VoiceIntentTier.TIER0_LOCAL_BYPASS
    assert res_clear.action is not None
    assert res_clear.action.action_id == "clear_session"

    # Open taskboard
    res_board = suite.route_utterance("打开任务板")
    assert res_board.tier == VoiceIntentTier.TIER0_LOCAL_BYPASS
    assert res_board.action is not None
    assert res_board.action.action_id == "open_taskboard"

    # Switch agent
    res_switch = suite.route_utterance("切换智能体")
    assert res_switch.tier == VoiceIntentTier.TIER0_LOCAL_BYPASS
    assert res_switch.action is not None
    assert res_switch.action.action_id == "switch_agent"
    assert res_switch.action.category == VoiceActionCategory.AGENT_SWITCH

    # Export session
    res_export = suite.route_utterance("导出对话")
    assert res_export.tier == VoiceIntentTier.TIER0_LOCAL_BYPASS
    assert res_export.action is not None
    assert res_export.action.action_id == "export_session"
    assert res_export.action.category == VoiceActionCategory.SYSTEM_EXPORT

    # Scroll bottom
    res_scroll = suite.route_utterance("滚动到底部")
    assert res_scroll.tier == VoiceIntentTier.TIER0_LOCAL_BYPASS
    assert res_scroll.action is not None
    assert res_scroll.action.action_id == "scroll_bottom"
    assert res_scroll.action.category == VoiceActionCategory.VIEW_SCROLL


def test_colloquial_filler_normalization() -> None:
    """Verify spoken prefixes and ending punctuation are stripped before matching."""
    suite = VoiceCommandLocalBypassAndTieredIntentRoutingSuite()

    # Chinese filler prefix and punctuation
    res_zh = suite.route_utterance("请帮我停止。")
    assert res_zh.tier == VoiceIntentTier.TIER0_LOCAL_BYPASS
    assert res_zh.action is not None
    assert res_zh.action.action_id == "stop_execution"

    # English filler prefix and question mark
    res_en = suite.route_utterance("please pause,")
    assert res_en.tier == VoiceIntentTier.TIER0_LOCAL_BYPASS
    assert res_en.action is not None
    assert res_en.action.action_id == "pause_execution"

    # Hey myrm conversational prefix
    res_wake = suite.route_utterance("hey myrm new chat!")
    assert res_wake.tier == VoiceIntentTier.TIER0_LOCAL_BYPASS
    assert res_wake.action is not None
    assert res_wake.action.action_id == "new_session"


def test_tier1_complex_task_reasoning_fallback() -> None:
    """Verify reasoning tasks or long sentences are never misrouted to Tier-0."""
    suite = VoiceCommandLocalBypassAndTieredIntentRoutingSuite()

    # Complex coding request
    res_code = suite.route_utterance("请帮我写一个快速排序算法并解释时间复杂度")
    assert res_code.tier == VoiceIntentTier.TIER1_AGENT_LLM
    assert res_code.is_bypass is False
    assert res_code.action is None
    assert res_code.tokens_saved == 0

    # Question with reasoning keyword
    res_why = suite.route_utterance("为什么这里的测试用例失败了？")
    assert res_why.tier == VoiceIntentTier.TIER1_AGENT_LLM
    assert res_why.is_bypass is False

    # English reasoning request
    res_explain = suite.route_utterance("explain how this architecture works in detail")
    assert res_explain.tier == VoiceIntentTier.TIER1_AGENT_LLM
    assert res_explain.is_bypass is False


def test_batch_routing_and_token_savings() -> None:
    """Verify batch routing tallies total saved tokens across commands."""
    suite = VoiceCommandLocalBypassAndTieredIntentRoutingSuite()
    utterances = [
        "停止",
        "新建会话",
        "帮我重构这个类的继承关系",
        "滚动到底部",
        "解释下这段代码",
    ]

    results = suite.batch_route(utterances)
    assert len(results) == 5

    bypass_count = sum(1 for r in results if r.tier == VoiceIntentTier.TIER0_LOCAL_BYPASS)
    llm_count = sum(1 for r in results if r.tier == VoiceIntentTier.TIER1_AGENT_LLM)

    assert bypass_count == 3
    assert llm_count == 2

    total_saved = suite.compute_cumulative_token_savings(results)
    expected_saved = 3 * suite.config.default_tokens_saved_estimate
    assert total_saved == expected_saved


def test_disabled_config_behavior() -> None:
    """Verify when bypass is disabled in config, all utterances route to Tier-1 LLM."""
    disabled_config = VoiceBypassConfig(enabled=False)
    suite = VoiceCommandLocalBypassAndTieredIntentRoutingSuite(config=disabled_config)

    res = suite.route_utterance("停止")
    assert res.tier == VoiceIntentTier.TIER1_AGENT_LLM
    assert res.is_bypass is False
    assert res.action is None
