"""Unit tests for Headroom Adaptive Context Token Budget & Progressive Compactor (Item 27)."""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from myrm_agent_harness.runtime.context.headroom_adaptive_budget_compressor import (
    AdaptiveBudgetManager,
    AdaptiveBudgetProfile,
    CompressionLevel,
    ProgressiveCompactionResult,
    ProgressiveSlidingWindowCompactor,
    TaskPhase,
)


def test_adaptive_budget_manager_profiles() -> None:
    """Verifies adaptive token allocation ratios across different task phases."""
    window = 100000

    profile_expl: AdaptiveBudgetProfile = AdaptiveBudgetManager.calculate_profile(window, TaskPhase.EXPLORATION)
    assert profile_expl.target_context_tokens == 85000
    assert profile_expl.max_output_tokens == 15000
    assert profile_expl.level_1_trigger_tokens == int(85000 * 0.80)
    assert profile_expl.level_2_trigger_tokens == int(85000 * 0.90)

    profile_impl: AdaptiveBudgetProfile = AdaptiveBudgetManager.calculate_profile(window, TaskPhase.IMPLEMENTATION)
    assert profile_impl.target_context_tokens == 65000
    assert profile_impl.max_output_tokens == 35000


def test_compactor_level_0_raw_untouched() -> None:
    """Verifies that messages well below trigger thresholds pass through unmodified."""
    compactor = ProgressiveSlidingWindowCompactor(recent_tail_turns=2)
    profile = AdaptiveBudgetManager.calculate_profile(context_window=100000, phase=TaskPhase.EXPLORATION)

    messages = [
        SystemMessage(content="You are an expert AI."),
        HumanMessage(content="Hello!"),
        AIMessage(content="Hi there, how can I help you today?"),
    ]

    res: ProgressiveCompactionResult = compactor.compact(messages, profile)
    assert res.level_applied == CompressionLevel.LEVEL_0_RAW
    assert res.saved_tokens == 0
    assert res.folded_tools_count == 0
    assert len(res.compressed_messages) == 3


def test_compactor_level_1_folds_verbose_tools() -> None:
    """Verifies that verbose tool outputs in historical prefix are folded while tail is preserved."""
    compactor = ProgressiveSlidingWindowCompactor(recent_tail_turns=2)

    # Force low threshold to engage Level 1
    profile = AdaptiveBudgetProfile(
        context_window=1000,
        task_phase=TaskPhase.IMPLEMENTATION,
        target_context_tokens=600,
        max_output_tokens=300,
        level_1_trigger_tokens=50,  # low threshold
        level_2_trigger_tokens=800,  # high enough not to hit Level 2
    )

    long_output = "Line 1: Build started.\n" + ("x" * 200) + "\nLine 3: Finished."
    messages = [
        HumanMessage(content="Run build"),
        AIMessage(content="Running build tool..."),
        ToolMessage(content=long_output, tool_call_id="call-001", name="bash"),
        HumanMessage(content="Tail message 1"),
        AIMessage(content="Tail message 2"),
    ]

    res: ProgressiveCompactionResult = compactor.compact(messages, profile)
    assert res.level_applied == CompressionLevel.LEVEL_1_FOLD_TOOL
    assert res.folded_tools_count == 1
    assert res.saved_tokens > 0

    # Verify tool output was replaced with folded marker
    folded_tool_msg = res.compressed_messages[2]
    assert isinstance(folded_tool_msg, ToolMessage)
    assert "[FOLDED_OUTPUT id=call-001 tool=bash]: Line 1: Build started." in str(folded_tool_msg.content)
    assert "[Unfurlable]" in str(folded_tool_msg.content)

    # Verify protected tail messages are intact
    assert res.compressed_messages[3].content == "Tail message 1"
    assert res.compressed_messages[4].content == "Tail message 2"


def test_compactor_level_2_semantic_summary() -> None:
    """Verifies that extreme overflow triggers Level 2 semantic milestone summary."""
    compactor = ProgressiveSlidingWindowCompactor(recent_tail_turns=2)

    # Force very low threshold to engage Level 2
    profile = AdaptiveBudgetProfile(
        context_window=500,
        task_phase=TaskPhase.IMPLEMENTATION,
        target_context_tokens=300,
        max_output_tokens=100,
        level_1_trigger_tokens=20,
        level_2_trigger_tokens=40,
    )

    messages = [
        SystemMessage(content="System prompt instructions."),
        HumanMessage(content="Old query 1 with extra context " * 5),
        AIMessage(content="Old response 1 with intermediate details " * 5),
        HumanMessage(content="Old query 2 with extra context " * 5),
        AIMessage(content="Old response 2 with intermediate details " * 5),
        HumanMessage(content="Recent tail message 1"),
        AIMessage(content="Recent tail message 2"),
    ]

    res: ProgressiveCompactionResult = compactor.compact(messages, profile)
    assert res.level_applied == CompressionLevel.LEVEL_2_SEMANTIC_SUMMARY
    assert res.saved_tokens > 0

    # First is system header, second is milestone summary, followed by protected tail
    assert isinstance(res.compressed_messages[0], SystemMessage)
    assert "System prompt instructions." in str(res.compressed_messages[0].content)

    summary_msg = res.compressed_messages[1]
    assert isinstance(summary_msg, SystemMessage)
    assert "<!-- PROGRESSIVE LEVEL 2 SUMMARY:" in str(summary_msg.content)

    # Tail is preserved
    assert res.compressed_messages[-2].content == "Recent tail message 1"
    assert res.compressed_messages[-1].content == "Recent tail message 2"


def test_high_fidelity_unfurling() -> None:
    """Verifies on-demand unfurling retrieves 100% of the raw output for folded tools."""
    compactor = ProgressiveSlidingWindowCompactor(recent_tail_turns=1)

    profile = AdaptiveBudgetProfile(
        context_window=1000,
        task_phase=TaskPhase.VERIFICATION,
        target_context_tokens=600,
        max_output_tokens=200,
        level_1_trigger_tokens=30,
        level_2_trigger_tokens=500,
    )

    raw_test_log = "FATAL ERROR: Null pointer exception at com.example.App:42\nStack trace line 1\nStack trace line 2" + ("!" * 120)
    messages = [
        HumanMessage(content="Check logs"),
        AIMessage(content="Reading logs"),
        ToolMessage(content=raw_test_log, tool_call_id="call-log-999", name="grep_logs"),
        AIMessage(content="Analysis complete"),
    ]

    res = compactor.compact(messages, profile)
    assert res.level_applied == CompressionLevel.LEVEL_1_FOLD_TOOL

    # Unfurl by tool_call_id
    unfurled = compactor.unfurl_tool_output("call-log-999")
    assert unfurled == raw_test_log

    # Unknown call ID returns None
    assert compactor.unfurl_tool_output("non_existent_id") is None
