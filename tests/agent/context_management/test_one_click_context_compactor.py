"""Unit tests for One-Click Context Compactor and HUD Token Economy."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.context_management.strategies.compactor import (
    OneClickCompactionConfig,
    OneClickContextCompactor,
)
from myrm_agent_harness.agent.context_management.tracking import (
    get_global_tokenomics_tracker,
)


def test_empty_messages_handling() -> None:
    msgs, result = OneClickContextCompactor.compact_session_history([])
    assert msgs == []
    assert result.original_messages_count == 0
    assert result.released_tokens == 0
    assert "无需瘦身" in result.feedback_badge


def test_recent_rounds_protection_and_historical_purification() -> None:
    # Construct a 3-turn conversation
    # Turn 1 (Historical): huge file read output
    # Turn 2 (Historical): huge bash build output
    # Turn 3 (Recent): active question and tool output
    huge_file_content = "line of code\n" * 100  # 1300 chars
    huge_build_content = "compiling module A\ncompiling module B\nwarning\nerror\n" * 20  # 1080 chars
    active_tool_content = "active status ok\n" * 30  # 510 chars

    messages = [
        # Turn 1
        HumanMessage(content="Read the big file"),
        AIMessage(content="Calling read_file..."),
        ToolMessage(content=huge_file_content, tool_call_id="call_read_1", name="read_file"),
        AIMessage(content="I analyzed the big file."),
        # Turn 2
        HumanMessage(content="Build the project"),
        AIMessage(content="Running bash build..."),
        ToolMessage(content=huge_build_content, tool_call_id="call_build_1", name="bash"),
        AIMessage(content="Build finished."),
        # Turn 3 (Recent 1)
        HumanMessage(content="What is current status?"),
        AIMessage(content="Checking status..."),
        ToolMessage(content=active_tool_content, tool_call_id="call_status_1", name="status_tool"),
        AIMessage(content="Status is normal."),
        # Turn 4 (Recent 2)
        HumanMessage(content="Final summary please."),
    ]

    cfg = OneClickCompactionConfig(keep_recent_rounds=2, min_content_length_to_purify=120)
    compacted_msgs, result = OneClickContextCompactor.compact_session_history(
        messages, session_id="test_session_42", config=cfg
    )

    assert len(compacted_msgs) == len(messages)
    assert result.purified_tool_count == 2  # Turn 1 and Turn 2 tools purified
    assert result.released_tokens > 200
    assert result.compression_ratio > 0.30
    assert "已成功为您瘦身" in result.feedback_badge

    # Turn 1 ToolMessage (index 2) was purified
    t1_content = str(compacted_msgs[2].content)
    assert "[COMPACTED_TOOL_RESULT: tool=read_file" in t1_content
    assert "line of code" in t1_content

    # Turn 2 ToolMessage (index 6) was purified
    t2_content = str(compacted_msgs[6].content)
    assert "[COMPACTED_TOOL_RESULT: tool=bash" in t2_content

    # Turn 3 ToolMessage (index 10) was protected (in recent 2 rounds)
    t3_content = str(compacted_msgs[10].content)
    assert t3_content == active_tool_content

    # HumanMessages preserved
    assert compacted_msgs[0].content == "Read the big file"
    assert compacted_msgs[4].content == "Build the project"
    assert compacted_msgs[8].content == "What is current status?"
    assert compacted_msgs[12].content == "Final summary please."


def test_small_tool_messages_preserved_without_purification() -> None:
    short_content = "ok: 42"
    messages = [
        HumanMessage(content="Check short value"),
        AIMessage(content="Calling tool"),
        ToolMessage(content=short_content, tool_call_id="c1", name="probe"),
        HumanMessage(content="Next step"),
        HumanMessage(content="Third turn"),
    ]

    cfg = OneClickCompactionConfig(keep_recent_rounds=1, min_content_length_to_purify=120)
    compacted_msgs, result = OneClickContextCompactor.compact_session_history(messages, config=cfg)

    # Tool is in history, but shorter than min_content_length_to_purify, so left intact
    assert result.purified_tool_count == 0
    assert compacted_msgs[2].content == short_content


def test_tokenomics_tracker_integration_records_savings() -> None:
    tracker = get_global_tokenomics_tracker()
    tracker.reset()

    large_log = "log row with excessive verbose payload\n" * 80  # ~3200 chars
    messages = [
        HumanMessage(content="Run query"),
        ToolMessage(content=large_log, tool_call_id="c_sql", name="sql_query"),
        HumanMessage(content="Next step 1"),
        HumanMessage(content="Next step 2"),
    ]

    cfg = OneClickCompactionConfig(keep_recent_rounds=1, model_name="deepseek-v3")
    _, result = OneClickContextCompactor.compact_session_history(
        messages, session_id="ses_abc", config=cfg
    )

    assert result.released_tokens > 100
    hud = tracker.get_hud_summary(session_id="ses_abc")
    assert hud.total_saved_tokens == result.released_tokens
    assert "one_click_compact" in hud.operator_breakdown
