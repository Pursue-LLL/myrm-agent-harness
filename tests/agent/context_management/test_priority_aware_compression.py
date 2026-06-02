"""Tests for priority-aware compression in compactor."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.context_management.infra.schemas import ContextConfig
from myrm_agent_harness.agent.context_management.strategies.compactor import (
    compress_messages_async,
    find_tool_message_pairs,
)


class TestPriorityAwareCompression:
    """Test priority-aware compression logic."""

    @pytest.mark.asyncio
    async def test_critical_messages_never_compressed(self) -> None:
        """CRITICAL messages (human + final iteration) should never be compressed."""
        messages = [
            HumanMessage(content="User query"),  # CRITICAL_USER
            AIMessage(
                content="I'll search for that",
                tool_calls=[{"name": "search", "args": {"query": "test"}, "id": "call_1"}],
            ),  # HIGH_TOOL_CALL
            ToolMessage(content="x" * 5000, tool_call_id="call_1"),  # LOW (large content)
            AIMessage(content="Final response"),  # CRITICAL_FINAL (last iteration)
        ]

        cfg = ContextConfig(max_context_tokens=10000, keep_recent_calls=0, compress_min_save=100)
        compressed, _saved_tokens = await compress_messages_async(messages, config=cfg, chat_id="test", user_id="user1")

        # Check human and final AI are NOT compressed
        assert any(isinstance(m, HumanMessage) and m.content == "User query" for m in compressed)
        assert any(isinstance(m, AIMessage) and m.content == "Final response" for m in compressed)

        # Tool message with large content SHOULD be compressed (LOW priority)
        tool_messages = [m for m in compressed if isinstance(m, ToolMessage)]
        if tool_messages:
            assert "COMPACTED:" in str(tool_messages[0].content) or len(str(tool_messages[0].content)) < 5000

    @pytest.mark.asyncio
    async def test_low_priority_compressed_first(self) -> None:
        """LOW priority (tool success) should be compressed before MEDIUM/HIGH."""
        messages = [
            HumanMessage(content="Start"),
            # Tool call pair 1 (LOW priority - success result)
            AIMessage(content="Call 1", tool_calls=[{"name": "search", "args": {"query": "q1"}, "id": "call_1"}]),
            ToolMessage(content="Success result " + "x" * 5000, tool_call_id="call_1"),
            # Tool call pair 2 (HIGH priority - error)
            AIMessage(content="Call 2", tool_calls=[{"name": "search", "args": {"query": "q2"}, "id": "call_2"}]),
            ToolMessage(content="[ERROR] Connection refused " + "y" * 5000, tool_call_id="call_2"),
            AIMessage(content="Final"),
        ]

        cfg = ContextConfig(max_context_tokens=10000, keep_recent_calls=1, compress_min_save=100)  # Keep 1, compress 1
        compressed, _ = await compress_messages_async(messages, config=cfg, chat_id="test", user_id="user1")

        # Find which tool message was compressed
        tool_msgs = [m for m in compressed if isinstance(m, ToolMessage)]
        compressed_tool = [m for m in tool_msgs if "COMPACTED:" in str(m.content) or len(str(m.content)) < 1000]
        error_tool = [m for m in tool_msgs if "[ERROR]" in str(m.content)]

        # LOW priority (success) should be compressed, HIGH priority (error) should be kept
        assert len(compressed_tool) >= 1, "At least one LOW priority tool should be compressed"
        if error_tool:
            # Error message should NOT be compressed (HIGH priority)
            assert len(str(error_tool[0].content)) > 1000, "Error tool message should be kept full"

    @pytest.mark.asyncio
    async def test_tool_call_pair_detection(self) -> None:
        """Test correct detection of AI+Tool message pairs."""
        messages = [
            HumanMessage(content="Query"),
            AIMessage(content="Thinking", tool_calls=[{"name": "search", "args": {}, "id": "call_1"}]),
            ToolMessage(content="Result 1", tool_call_id="call_1"),
            AIMessage(content="More thinking", tool_calls=[{"name": "calculate", "args": {}, "id": "call_2"}]),
            ToolMessage(content="Result 2", tool_call_id="call_2"),
            AIMessage(content="Final"),
        ]

        pairs = find_tool_message_pairs(messages)
        assert len(pairs) == 2, "Should detect 2 tool call pairs"

        # Verify pair structure (ai_idx, tool_idx, ai_msg, tool_msg)
        _ai_idx1, _tool_idx1, ai_msg1, tool_msg1 = pairs[0]
        assert isinstance(ai_msg1, AIMessage)
        assert isinstance(tool_msg1, ToolMessage)
        assert tool_msg1.tool_call_id == "call_1"

        _ai_idx2, _tool_idx2, _ai_msg2, tool_msg2 = pairs[1]
        assert tool_msg2.tool_call_id == "call_2"


class TestPrioritySorting:
    """Test priority-based sorting logic."""

    @pytest.mark.asyncio
    async def test_compression_order_respects_priority(self) -> None:
        """When multiple pairs need compression, LOW priority should go first."""
        messages = [
            HumanMessage(content="Start"),
            # Pair 1: LOW priority (success)
            AIMessage(content="Call 1", tool_calls=[{"name": "search", "args": {"query": "q1"}, "id": "call_1"}]),
            ToolMessage(content="Success " + "a" * 6000, tool_call_id="call_1"),
            # Pair 2: MEDIUM priority (reasoning + result with summary)
            AIMessage(content="I'm analyzing..."),
            # Pair 3: LOW priority (success)
            AIMessage(content="Call 3", tool_calls=[{"name": "search", "args": {"query": "q3"}, "id": "call_3"}]),
            ToolMessage(content="Another success " + "b" * 6000, tool_call_id="call_3"),
            AIMessage(content="Final"),
        ]

        cfg = ContextConfig(max_context_tokens=10000, keep_recent_calls=1, compress_min_save=100)
        compressed, saved = await compress_messages_async(messages, config=cfg, chat_id="test", user_id="user1")

        # At least one LOW priority tool should be compressed
        tool_msgs = [m for m in compressed if isinstance(m, ToolMessage)]
        compressed_count = sum(1 for m in tool_msgs if "COMPACTED:" in str(m.content) or len(str(m.content)) < 1000)

        assert compressed_count >= 1, "At least one LOW priority tool message should be compressed"
        assert saved > 0, "Should save tokens by compressing LOW priority messages"

    @pytest.mark.asyncio
    async def test_failed_tool_call_ids_keep_failed_group_uncompressed_longer(self) -> None:
        """Groups marked as failed by compression intent should be kept over plain successes."""
        messages = [
            HumanMessage(content="Start"),
            AIMessage(content="Call 1", tool_calls=[{"name": "search", "args": {"query": "q1"}, "id": "call_1"}]),
            ToolMessage(content="Success result " + "x" * 5000, tool_call_id="call_1"),
            AIMessage(content="Call 2", tool_calls=[{"name": "search", "args": {"query": "q2"}, "id": "call_failed"}]),
            ToolMessage(content="Looks normal but should stay " + "y" * 5000, tool_call_id="call_failed"),
            AIMessage(content="Final"),
        ]

        cfg = ContextConfig(max_context_tokens=10000, keep_recent_calls=1, compress_min_save=100)
        compressed, _ = await compress_messages_async(
            messages, config=cfg, chat_id="test", user_id="user1", failed_tool_call_ids=frozenset({"call_failed"})
        )

        tool_messages = {msg.tool_call_id: msg for msg in compressed if isinstance(msg, ToolMessage)}
        assert "COMPACTED:" in str(tool_messages["call_1"].content) or len(str(tool_messages["call_1"].content)) < 1000
        assert len(str(tool_messages["call_failed"].content)) > 1000

    @pytest.mark.asyncio
    async def test_focus_files_keep_relevant_group_uncompressed_longer(self) -> None:
        """Focused files should keep matching tool groups over unrelated success groups."""
        messages = [
            HumanMessage(content="Start"),
            AIMessage(
                content="Call unrelated",
                tool_calls=[{"name": "read_file", "args": {"path": "docs/old.md"}, "id": "call_other"}],
            ),
            ToolMessage(content="docs/old.md content " + "x" * 5000, tool_call_id="call_other"),
            AIMessage(
                content="Call focused",
                tool_calls=[{"name": "read_file", "args": {"path": "src/app.py"}, "id": "call_focus"}],
            ),
            ToolMessage(content="src/app.py content " + "y" * 5000, tool_call_id="call_focus"),
            AIMessage(content="Final"),
        ]

        cfg = ContextConfig(max_context_tokens=10000, keep_recent_calls=1, compress_min_save=100)
        compressed, _ = await compress_messages_async(
            messages, config=cfg, chat_id="test", user_id="user1", focus_files=frozenset({"src/app.py"})
        )

        tool_messages = {msg.tool_call_id: msg for msg in compressed if isinstance(msg, ToolMessage)}
        assert (
            "COMPACTED:" in str(tool_messages["call_other"].content)
            or len(str(tool_messages["call_other"].content)) < 1000
        )
        assert len(str(tool_messages["call_focus"].content)) > 1000

    @pytest.mark.asyncio
    async def test_user_goal_hint_keeps_goal_related_group_uncompressed_longer(self) -> None:
        """Goal hint should protect matching groups even without explicit file/module focus."""
        messages = [
            HumanMessage(content="Start"),
            AIMessage(
                content="Call unrelated",
                tool_calls=[{"name": "bash", "args": {"command": "pytest tests/test_other.py"}, "id": "call_other"}],
            ),
            ToolMessage(content="all green " + "x" * 5000, tool_call_id="call_other", name="bash"),
            AIMessage(
                content="Call goal-related",
                tool_calls=[
                    {"name": "bash", "args": {"command": "pytest tests/test_login_timeout.py"}, "id": "call_goal"}
                ],
            ),
            ToolMessage(content="timeout failure in login flow " + "y" * 5000, tool_call_id="call_goal", name="bash"),
            AIMessage(content="Final"),
        ]

        cfg = ContextConfig(max_context_tokens=10000, keep_recent_calls=1, compress_min_save=100)
        compressed, _ = await compress_messages_async(
            messages, config=cfg, chat_id="test", user_id="user1", user_goal_hint="fix login timeout issue"
        )

        tool_messages = {msg.tool_call_id: msg for msg in compressed if isinstance(msg, ToolMessage)}
        assert (
            "COMPACTED:" in str(tool_messages["call_other"].content)
            or len(str(tool_messages["call_other"].content)) < 1000
        )
        assert len(str(tool_messages["call_goal"].content)) > 1000

    @pytest.mark.asyncio
    async def test_focus_files_match_tail_window_for_large_output(self) -> None:
        """Focused files should still match when the path appears near the end of large output."""
        messages = [
            HumanMessage(content="Start"),
            AIMessage(
                content="Call unrelated",
                tool_calls=[{"name": "bash", "args": {"command": "pytest tests/test_other.py"}, "id": "call_other"}],
            ),
            ToolMessage(content="other output " + "x" * 5000, tool_call_id="call_other", name="bash"),
            AIMessage(
                content="Call focused",
                tool_calls=[{"name": "bash", "args": {"command": "pytest tests/test_login.py"}, "id": "call_focus"}],
            ),
            ToolMessage(
                content=("y" * 70000) + "\nFAILED src/login.py::test_timeout\n", tool_call_id="call_focus", name="bash"
            ),
            AIMessage(content="Final"),
        ]

        cfg = ContextConfig(max_context_tokens=10000, keep_recent_calls=1, compress_min_save=100)
        compressed, _ = await compress_messages_async(
            messages, config=cfg, chat_id="test", user_id="user1", focus_files=frozenset({"src/login.py"})
        )

        tool_messages = {msg.tool_call_id: msg for msg in compressed if isinstance(msg, ToolMessage)}
        assert (
            "COMPACTED:" in str(tool_messages["call_other"].content)
            or len(str(tool_messages["call_other"].content)) < 1000
        )
        assert len(str(tool_messages["call_focus"].content)) > 1000
