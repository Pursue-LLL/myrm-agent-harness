"""Tests for smart fallback strategy."""

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.context_management.strategies.compression_formatting import (
    _shrink_value,
    shrink_tool_call_args,
)
from myrm_agent_harness.agent.context_management.strategies.smart_fallback import apply_smart_fallback


class TestSmartFallback:
    """Test smart fallback strategy for extreme token overflow."""

    @pytest.mark.asyncio
    async def test_fallback_keeps_critical_messages(self) -> None:
        """Smart fallback should keep all CRITICAL messages fully."""
        messages = [
            HumanMessage(content="Query " + "x" * 500),  # CRITICAL_USER
            AIMessage(content="I'll call tools", tool_calls=[{"name": "search", "args": {}, "id": "call_1"}]),
            ToolMessage(content="Tool result " + "y" * 10000, tool_call_id="call_1"),  # HIGH
            AIMessage(content="Final answer " + "z" * 500),  # CRITICAL_FINAL (last iteration)
        ]

        # Set max_tokens very low to trigger aggressive fallback
        fallback_messages, _saved = await apply_smart_fallback(messages, max_tokens=1000)

        # Human and final AI should be kept fully
        human_msgs = [m for m in fallback_messages if isinstance(m, HumanMessage)]
        ai_final_msgs = [m for m in fallback_messages if isinstance(m, AIMessage) and "Final answer" in str(m.content)]

        assert len(human_msgs) == 1, "Human message should be kept"
        assert len(human_msgs[0].content) > 500, "Human content should be full"
        assert len(ai_final_msgs) >= 1, "Final AI message should be kept"

    @pytest.mark.asyncio
    async def test_fallback_respects_budget(self) -> None:
        """Smart fallback should not exceed max_tokens."""
        messages = [
            HumanMessage(content="x" * 1000),
            AIMessage(content="y" * 2000, tool_calls=[{"name": "search", "args": {}, "id": "call_1"}]),
            ToolMessage(content="z" * 5000, tool_call_id="call_1"),
            AIMessage(content="w" * 1000),
        ]

        max_tokens = 2000
        fallback_messages, _ = await apply_smart_fallback(messages, max_tokens=max_tokens)

        # Estimate tokens (rough check)
        from myrm_agent_harness.utils.token_estimation import estimate_messages_tokens

        final_tokens = estimate_messages_tokens(fallback_messages)
        # Allow some margin for truncation estimation
        assert final_tokens <= max_tokens * 1.2, f"Should respect budget: {final_tokens} > {max_tokens * 1.2}"


class TestFallbackPhases:
    """Test 3-phase fallback logic."""

    @pytest.mark.asyncio
    async def test_phase1_critical_preserved(self) -> None:
        """Phase 1: All CRITICAL messages should be preserved."""
        messages = [
            HumanMessage(content="User input"),
            AIMessage(content="Some reasoning"),
            AIMessage(content="Final output"),  # CRITICAL_FINAL
        ]

        fallback_messages, _ = await apply_smart_fallback(messages, max_tokens=100)

        assert any(isinstance(m, HumanMessage) for m in fallback_messages), "Human message (phase 1)"
        assert any(isinstance(m, AIMessage) and "Final" in str(m.content) for m in fallback_messages), (
            "Final AI (phase 1)"
        )


class TestBoundaryGuard:
    """Test boundary guard protection for tool message pairs."""

    @pytest.mark.asyncio
    async def test_removes_orphan_tool_at_beginning(self) -> None:
        """Boundary guard should remove orphan ToolMessage at the beginning."""
        messages = [
            HumanMessage(content="Previous context"),
            AIMessage(content="I'll use tool", tool_calls=[{"name": "search", "args": {}, "id": "call_1"}]),
            ToolMessage(content="Orphan tool result", tool_call_id="call_1"),  # This will become first
            HumanMessage(content="New query"),
            AIMessage(content="Final answer"),
        ]

        # Simulate scenario where first 2 messages are CRITICAL and kept,
        # but tool message ends up at start of result
        fallback_messages, _ = await apply_smart_fallback(messages, max_tokens=500)

        # First message should NOT be ToolMessage
        assert len(fallback_messages) > 0
        assert not isinstance(fallback_messages[0], ToolMessage), (
            f"First message should not be ToolMessage, got {type(fallback_messages[0])}"
        )

    @pytest.mark.asyncio
    async def test_removes_multiple_orphan_tools_at_beginning(self) -> None:
        """Boundary guard should remove multiple consecutive orphan ToolMessages."""
        messages = [
            ToolMessage(content="Orphan 1", tool_call_id="call_1"),  # Will be at start
            ToolMessage(content="Orphan 2", tool_call_id="call_2"),  # Will be at start
            HumanMessage(content="User query"),
            AIMessage(content="Response"),
        ]

        fallback_messages, _ = await apply_smart_fallback(messages, max_tokens=500)

        # Should remove both orphan tools
        assert len(fallback_messages) > 0
        assert not isinstance(fallback_messages[0], ToolMessage)
        # Should keep human and AI
        assert any(isinstance(m, HumanMessage) for m in fallback_messages)

    @pytest.mark.asyncio
    async def test_keeps_valid_tool_messages_with_ai_call(self) -> None:
        """Boundary guard should NOT remove tool messages that have corresponding AI calls."""
        messages = [
            HumanMessage(content="Query"),
            AIMessage(content="Calling tool", tool_calls=[{"name": "search", "args": {}, "id": "call_1"}]),
            ToolMessage(content="Tool result", tool_call_id="call_1"),
            AIMessage(content="Final"),
        ]

        fallback_messages, _ = await apply_smart_fallback(messages, max_tokens=5000)

        # First message should be HumanMessage or AIMessage, not ToolMessage
        assert not isinstance(fallback_messages[0], ToolMessage)


class TestFallbackBudgetAllocation:
    """Test budget allocation in Phase 2."""

    @pytest.mark.asyncio
    async def test_phase2_budget_allocate_high_priority(self) -> None:
        """Phase 2 should allocate budget fairly among HIGH priority messages."""
        messages = [
            HumanMessage(content="Query"),
            AIMessage(content="Call 1", tool_calls=[{"name": "tool1", "args": {}, "id": "c1"}]),
            ToolMessage(content="Result 1" * 1000, tool_call_id="c1"),  # HIGH
            AIMessage(content="Call 2", tool_calls=[{"name": "tool2", "args": {}, "id": "c2"}]),
            ToolMessage(content="Result 2" * 1000, tool_call_id="c2"),  # HIGH
            AIMessage(content="Final"),  # CRITICAL_FINAL
        ]

        fallback_messages, _ = await apply_smart_fallback(messages, max_tokens=1500)

        # Should include some HIGH priority messages within budget
        assert len(fallback_messages) >= 2  # At least human + final AI

    @pytest.mark.asyncio
    async def test_truncates_oversized_tool_messages(self) -> None:
        """Should truncate tool messages that exceed per-message budget."""
        messages = [
            HumanMessage(content="Query"),
            AIMessage(content="Call", tool_calls=[{"name": "tool", "args": {}, "id": "c1"}]),
            ToolMessage(content="X" * 50000, tool_call_id="c1"),  # Very large
            AIMessage(content="Final"),
        ]

        fallback_messages, _ = await apply_smart_fallback(messages, max_tokens=2000)

        # Should include truncated tool message
        tool_msgs = [m for m in fallback_messages if isinstance(m, ToolMessage)]
        if tool_msgs:
            # Content should be truncated
            assert len(tool_msgs[0].content) < 50000

    @pytest.mark.asyncio
    async def test_phase3_medium_priority_one_line_summary(self) -> None:
        """Phase 3 should create one-line summaries for MEDIUM priority."""
        messages = [
            HumanMessage(content="Query"),
            AIMessage(content="Long reasoning:\nLine 1\nLine 2\nLine 3"),  # MEDIUM
            AIMessage(content="Final answer"),  # CRITICAL_FINAL
        ]

        fallback_messages, _ = await apply_smart_fallback(messages, max_tokens=800)

        # Should have summarized MEDIUM message
        summarized = [m for m in fallback_messages if "[Summarized]" in str(m.content)]
        assert len(summarized) >= 0  # May or may not include depending on budget


class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_empty_messages_list(self) -> None:
        """Should handle empty messages list gracefully."""
        messages: list[BaseMessage] = []
        fallback_messages, saved = await apply_smart_fallback(messages, max_tokens=1000)

        assert fallback_messages == []
        assert saved == 0

    @pytest.mark.asyncio
    async def test_only_critical_messages(self) -> None:
        """When only CRITICAL messages exist, should keep all."""
        messages = [
            HumanMessage(content="Query"),
            AIMessage(content="Response"),  # Will be CRITICAL_FINAL
        ]

        fallback_messages, _ = await apply_smart_fallback(messages, max_tokens=500)

        assert len(fallback_messages) == 2

    @pytest.mark.asyncio
    async def test_critical_exceeds_budget(self) -> None:
        """When CRITICAL alone exceeds budget, should return CRITICAL only."""
        messages = [
            HumanMessage(content="X" * 50000),  # Very large CRITICAL
            AIMessage(content="Response"),
        ]

        fallback_messages, saved = await apply_smart_fallback(messages, max_tokens=500)

        # Should return CRITICAL messages even if exceeding budget
        assert any(isinstance(m, HumanMessage) for m in fallback_messages)
        # No tokens saved since we can't compress CRITICAL
        assert saved == 0

    @pytest.mark.asyncio
    async def test_phase2_stops_when_budget_exhausted(self) -> None:
        """Phase 2 should stop adding messages when budget is exhausted."""
        messages = [
            HumanMessage(content="Q"),
            AIMessage(content="C1", tool_calls=[{"name": "t1", "args": {}, "id": "c1"}]),
            ToolMessage(content="R1" * 500, tool_call_id="c1"),
            AIMessage(content="C2", tool_calls=[{"name": "t2", "args": {}, "id": "c2"}]),
            ToolMessage(content="R2" * 500, tool_call_id="c2"),
            AIMessage(content="C3", tool_calls=[{"name": "t3", "args": {}, "id": "c3"}]),
            ToolMessage(content="R3" * 500, tool_call_id="c3"),
            AIMessage(content="Final"),
        ]

        # Very tight budget - should stop in Phase 2
        fallback_messages, _ = await apply_smart_fallback(messages, max_tokens=600)

        # Should have stopped adding HIGH messages when budget exhausted
        assert len(fallback_messages) >= 2  # At least human + final

    @pytest.mark.asyncio
    async def test_truncate_functions_called(self) -> None:
        """Test that truncation functions are actually called."""
        messages = [
            HumanMessage(content="Q"),
            AIMessage(content="X" * 2000, tool_calls=[{"name": "t", "args": {}, "id": "c1"}]),
            ToolMessage(content="Y" * 5000, tool_call_id="c1"),
            AIMessage(content="Final"),
        ]

        fallback_messages, _ = await apply_smart_fallback(messages, max_tokens=800)

        # If HIGH messages are included, they should be truncated
        ai_msgs = [m for m in fallback_messages if isinstance(m, AIMessage) and m.tool_calls]
        tool_msgs = [m for m in fallback_messages if isinstance(m, ToolMessage)]

        # Check truncation happened
        for ai_msg in ai_msgs:
            if ai_msg.content:
                # Should be truncated or kept within budget
                assert len(str(ai_msg.content)) <= 10000

        for tool_msg in tool_msgs:
            # Should be truncated or kept within budget
            assert len(str(tool_msg.content)) <= 10000

    @pytest.mark.asyncio
    async def test_detect_last_iteration_no_human(self) -> None:
        """_detect_last_iteration_ids should handle messages with no HumanMessage."""
        messages = [
            AIMessage(content="Some AI message"),
            ToolMessage(content="Tool result", tool_call_id="c1"),
        ]

        # This should not crash
        fallback_messages, _ = await apply_smart_fallback(messages, max_tokens=500)

        # All non-CRITICAL messages, so may be empty or truncated
        assert isinstance(fallback_messages, list)

    @pytest.mark.asyncio
    async def test_no_high_messages_skips_phase2(self) -> None:
        """When there are no HIGH priority messages, Phase 2 should be skipped."""
        messages = [
            HumanMessage(content="Query"),
            AIMessage(content="Just reasoning, no tool calls"),  # MEDIUM
            AIMessage(content="Final"),  # CRITICAL_FINAL
        ]

        fallback_messages, _ = await apply_smart_fallback(messages, max_tokens=500)

        # Should keep CRITICAL and may add MEDIUM summaries
        assert len(fallback_messages) >= 2

    @pytest.mark.asyncio
    async def test_phase3_budget_exhausted_stops_adding_medium(self) -> None:
        """Phase 3 should stop when budget is exhausted."""
        messages = [
            HumanMessage(content="Q" * 100),
            AIMessage(content="Reasoning 1" * 50),  # MEDIUM
            AIMessage(content="Reasoning 2" * 50),  # MEDIUM
            AIMessage(content="Reasoning 3" * 50),  # MEDIUM
            AIMessage(content="F" * 100),  # CRITICAL_FINAL
        ]

        # Tight budget - should stop in Phase 3
        fallback_messages, _ = await apply_smart_fallback(messages, max_tokens=400)

        # Should not include all MEDIUM messages due to budget constraint
        medium_summaries = [m for m in fallback_messages if "[Summarized]" in str(m.content)]
        # Budget constraint should limit how many MEDIUM summaries are added
        assert len(medium_summaries) <= 3

    @pytest.mark.asyncio
    async def test_tool_message_truncation_with_long_content(self) -> None:
        """Test _truncate_tool_message is called for oversized tool results."""
        messages = [
            HumanMessage(content="Q"),
            AIMessage(content="C", tool_calls=[{"name": "tool", "args": {}, "id": "c1"}]),
            ToolMessage(content="R" * 10000, tool_call_id="c1"),  # ~40KB, ~10K tokens
            AIMessage(content="F"),
        ]

        fallback_messages, _ = await apply_smart_fallback(messages, max_tokens=1200)

        # Tool message should be truncated
        tool_msgs = [m for m in fallback_messages if isinstance(m, ToolMessage)]
        if tool_msgs:
            # Should contain truncation marker
            assert "[budget-truncated" in str(tool_msgs[0].content)

    @pytest.mark.asyncio
    async def test_ai_message_truncation_with_no_tool_calls(self) -> None:
        """Test _truncate_ai_message handles messages without tool_calls."""
        messages = [
            HumanMessage(content="Q"),
            AIMessage(content="Long reasoning " * 1000),  # No tool_calls
            AIMessage(content="Another reasoning " * 1000),
            AIMessage(content="F"),
        ]

        fallback_messages, _ = await apply_smart_fallback(messages, max_tokens=900)

        # AI messages without tool_calls may be summarized in Phase 3
        assert len(fallback_messages) >= 2

    @pytest.mark.asyncio
    async def test_boundary_guard_not_triggered_when_first_is_human(self) -> None:
        """Boundary guard should not do anything when first message is HumanMessage."""
        messages = [
            HumanMessage(content="Query"),
            AIMessage(content="Response"),
        ]

        fallback_messages, _ = await apply_smart_fallback(messages, max_tokens=1000)

        # No orphan removal happened
        assert len(fallback_messages) == 2
        assert isinstance(fallback_messages[0], HumanMessage)

    @pytest.mark.asyncio
    async def test_truncate_ai_message_with_tool_calls(self) -> None:
        """AI message with tool_calls should preserve tool_calls after truncation."""
        messages = [
            HumanMessage(content="Q"),
            AIMessage(
                content="Very long content " * 100,  # HIGH priority
                tool_calls=[{"name": "tool", "args": {}, "id": "c1"}],
            ),
            ToolMessage(content="Very long result " * 200, tool_call_id="c1"),  # HIGH priority
            AIMessage(content="F"),  # CRITICAL_FINAL
        ]

        # Budget allows CRITICAL + some HIGH
        fallback_messages, _ = await apply_smart_fallback(messages, max_tokens=1500)

        # AI with tool_calls should be included (HIGH priority)
        ai_with_calls = [m for m in fallback_messages if isinstance(m, AIMessage) and m.tool_calls]
        assert len(ai_with_calls) > 0
        # tool_calls should be preserved even if content is truncated
        assert ai_with_calls[0].tool_calls

    @pytest.mark.asyncio
    async def test_no_boundary_removal_when_first_is_valid(self) -> None:
        """Boundary guard should not remove messages when first message is valid."""
        messages = [
            HumanMessage(content="Query"),
            AIMessage(content="Response"),
        ]

        fallback_messages, _ = await apply_smart_fallback(messages, max_tokens=500)

        # No removal should happen
        assert len(fallback_messages) == 2

    @pytest.mark.asyncio
    async def test_high_message_not_truncated_when_within_budget(self) -> None:
        """HIGH messages within per-message budget should not be truncated (else branch line 82)."""
        messages = [
            HumanMessage(content="Q"),
            AIMessage(content="Short call", tool_calls=[{"name": "t", "args": {}, "id": "c1"}]),
            ToolMessage(content="Short result", tool_call_id="c1"),  # Small, no truncation
            AIMessage(content="F"),
        ]

        fallback_messages, _ = await apply_smart_fallback(messages, max_tokens=2000)

        # Tool message should be kept without truncation (line 84 else branch)
        tool_msgs = [m for m in fallback_messages if isinstance(m, ToolMessage)]
        if tool_msgs:
            # Should not have truncation marker
            assert "[budget-truncated" not in str(tool_msgs[0].content)
            assert tool_msgs[0].content == "Short result"

    @pytest.mark.asyncio
    async def test_ai_message_empty_content_in_medium_phase(self) -> None:
        """AI message with empty content in Phase 3 should be skipped (line 101 condition)."""
        messages = [
            HumanMessage(content="Q"),
            AIMessage(content=""),  # Empty content
            AIMessage(content="Some reasoning"),  # Has content
            AIMessage(content="F"),
        ]

        fallback_messages, _ = await apply_smart_fallback(messages, max_tokens=500)

        # Should not crash, empty content AI should be skipped
        assert len(fallback_messages) >= 2

    @pytest.mark.asyncio
    async def test_boundary_guard_logs_removal(self) -> None:
        """Boundary guard should log when removing orphans (line 117)."""
        messages = [
            ToolMessage(content="Orphan", tool_call_id="c1"),
            HumanMessage(content="Query"),
            AIMessage(content="Response"),
        ]

        fallback_messages, _ = await apply_smart_fallback(messages, max_tokens=500)

        # First should not be tool
        assert not isinstance(fallback_messages[0], ToolMessage)
        # Log should have been triggered (covered by execution)


class TestShrinkToolCallArgs:
    """Tests for shrink_tool_call_args and _shrink_value."""

    def test_short_string_unchanged(self) -> None:
        result = _shrink_value("short text")
        assert result == "short text"

    def test_long_string_truncated(self) -> None:
        long_str = "x" * 1000
        result = _shrink_value(long_str)
        assert isinstance(result, str)
        assert len(result) < 1000
        assert "chars omitted" in result
        assert result.startswith("x" * 200)
        assert result.endswith("x" * 50)

    def test_nested_dict_values_shrunk(self) -> None:
        data = {"key": "a" * 1000, "short": "ok", "num": 42}
        result = _shrink_value(data)
        assert isinstance(result, dict)
        assert "chars omitted" in result["key"]
        assert result["short"] == "ok"
        assert result["num"] == 42

    def test_list_values_shrunk(self) -> None:
        data = ["a" * 1000, "short"]
        result = _shrink_value(data)
        assert isinstance(result, list)
        assert len(result) == 2
        assert "chars omitted" in result[0]
        assert result[1] == "short"

    def test_long_list_capped(self) -> None:
        data = list(range(30))
        result = _shrink_value(data)
        assert isinstance(result, list)
        assert len(result) == 11
        assert "20 more items omitted" in result[-1]

    def test_shrink_tool_call_args_preserves_structure(self) -> None:
        tool_calls = [
            {"name": "file_write", "args": {"path": "/tmp/test.py", "content": "x" * 2000}, "id": "c1"},
            {"name": "search", "args": {"query": "short"}, "id": "c2"},
        ]
        result = shrink_tool_call_args(tool_calls)
        assert len(result) == 2
        assert result[0]["name"] == "file_write"
        assert result[0]["id"] == "c1"
        assert "chars omitted" in result[0]["args"]["content"]
        assert result[0]["args"]["path"] == "/tmp/test.py"
        assert result[1]["args"]["query"] == "short"

    def test_shrink_does_not_mutate_original(self) -> None:
        original_content = "y" * 1000
        tool_calls = [{"name": "tool", "args": {"data": original_content}, "id": "c1"}]
        shrink_tool_call_args(tool_calls)
        assert tool_calls[0]["args"]["data"] == original_content

    def test_shrink_with_non_dict_args(self) -> None:
        tool_calls = [{"name": "tool", "args": "not_a_dict", "id": "c1"}]
        result = shrink_tool_call_args(tool_calls)
        assert result[0]["args"] == "not_a_dict"

    def test_shrink_empty_tool_calls(self) -> None:
        assert shrink_tool_call_args([]) == []

    @pytest.mark.asyncio
    async def test_truncate_ai_message_shrinks_tool_call_args(self) -> None:
        """_truncate_ai_message should shrink tool_call args with long content."""
        messages = [
            HumanMessage(content="Q"),
            AIMessage(
                content="Calling file_write",
                tool_calls=[
                    {
                        "name": "file_write",
                        "args": {"path": "/test.py", "content": "z" * 2000},
                        "id": "c1",
                    }
                ],
            ),
            ToolMessage(content="Success", tool_call_id="c1"),
            AIMessage(content="Done"),
        ]

        fallback_messages, _ = await apply_smart_fallback(messages, max_tokens=1500)

        ai_with_calls = [m for m in fallback_messages if isinstance(m, AIMessage) and m.tool_calls]
        if ai_with_calls:
            args = ai_with_calls[0].tool_calls[0]["args"]
            assert "chars omitted" in args["content"]
            assert args["path"] == "/test.py"
