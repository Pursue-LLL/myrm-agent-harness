"""Tests for summary_builder module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from myrm_agent_harness.agent.context_management.infra.schemas import StructuredSummary
from myrm_agent_harness.agent.context_management.strategies.summary_builder import (
    UNVERIFIED_CONTEXT_MARKER,
    create_summary_message,
    extract_recent_messages,
)


class TestExtractRecentMessages:
    def test_keeps_tool_call_pairs(self) -> None:
        msgs = [
            HumanMessage(content="q1"),
            AIMessage(content="", tool_calls=[{"name": "t1", "args": {}, "id": "c1"}]),
            ToolMessage(content="r1", name="t1", tool_call_id="c1"),
            AIMessage(content="", tool_calls=[{"name": "t2", "args": {}, "id": "c2"}]),
            ToolMessage(content="r2", name="t2", tool_call_id="c2"),
        ]
        # Low budget: triggers min_tail=2. Alignment shouldn't pull further back
        # because msgs[3] is an AIMessage, not a ToolMessage.
        result = extract_recent_messages(msgs, tail_budget_tokens=10)
        assert len(result) == 2
        assert isinstance(result[0], AIMessage)
        assert isinstance(result[1], ToolMessage)

    def test_aligns_boundary_backward(self) -> None:
        msgs = [
            HumanMessage(content="q1"),
            AIMessage(content="", tool_calls=[{"name": "t1", "args": {}, "id": "c1"}]),
            ToolMessage(content="r1", name="t1", tool_call_id="c1"),
        ]
        # Budget is 10, min_tail is 2, length is 3. fallback_cut is 1.
        # cut_idx becomes 1. msgs[1] is AIMessage. No alignment needed.
        # So it returns msgs[1:3].
        result = extract_recent_messages(msgs, tail_budget_tokens=10)
        assert len(result) == 2

    def test_keeps_multiple_pairs(self) -> None:
        msgs = [
            AIMessage(content="some long text to increase tokens", tool_calls=[{"name": "t1", "args": {}, "id": "c1"}]),
            ToolMessage(content="r1", name="t1", tool_call_id="c1"),
            AIMessage(content="some other long text", tool_calls=[{"name": "t2", "args": {}, "id": "c2"}]),
            ToolMessage(content="r2", name="t2", tool_call_id="c2"),
        ]
        # High budget keeps everything
        result = extract_recent_messages(msgs, tail_budget_tokens=1000)
        assert len(result) == 4

    def test_keeps_human_messages(self) -> None:
        msgs = [HumanMessage(content="hello"), HumanMessage(content="world")]
        result = extract_recent_messages(msgs, tail_budget_tokens=1000)
        assert len(result) == 2

    def test_keeps_ai_text_replies(self) -> None:
        msgs = [AIMessage(content="response text")]
        result = extract_recent_messages(msgs, tail_budget_tokens=1000)
        assert len(result) == 1
        assert isinstance(result[0], AIMessage)

    def test_empty_messages(self) -> None:
        assert extract_recent_messages([], tail_budget_tokens=1000) == []

    def test_orphan_tool_message_skipped(self) -> None:
        msgs = [ToolMessage(content="orphan", name="t1", tool_call_id="c1")]
        result = extract_recent_messages(msgs, tail_budget_tokens=1000)
        assert len(result) == 1


class TestCreateSummaryMessage:
    def test_basic_structure(self) -> None:
        summary = StructuredSummary(user_goal="Build a web app", last_action="Created index.html")
        msg = create_summary_message(summary)
        assert isinstance(msg, HumanMessage)
        content = msg.content
        assert "[Historical Summary]" in content
        assert "Build a web app" in content
        assert "Created index.html" in content

    def test_unverified_context_marker(self) -> None:
        summary = StructuredSummary(user_goal="test")
        msg = create_summary_message(summary)
        assert UNVERIFIED_CONTEXT_MARKER in msg.content

    def test_lost_in_middle_ordering(self) -> None:
        summary = StructuredSummary(
            user_goal="Goal", last_action="Last", completed_actions=["action1"], key_findings=["finding1"]
        )
        msg = create_summary_message(summary)
        content = msg.content
        goal_pos = content.index("Goal")
        action_pos = content.index("action1")
        finding_pos = content.index("finding1")
        assert goal_pos < action_pos < finding_pos

    def test_includes_json_block(self) -> None:
        summary = StructuredSummary(user_goal="test")
        msg = create_summary_message(summary)
        assert "<!-- SUMMARY_JSON" in msg.content
        assert "-->" in msg.content

    def test_files_modified_section(self) -> None:
        summary = StructuredSummary(user_goal="test", files_modified=["a.py", "b.py"])
        msg = create_summary_message(summary)
        assert "a.py" in msg.content
        assert "b.py" in msg.content

    def test_context_dump_path(self) -> None:
        summary = StructuredSummary(user_goal="test", context_dump_path="/tmp/ctx.log")
        msg = create_summary_message(summary)
        assert "/tmp/ctx.log" in msg.content

    @patch("myrm_agent_harness.agent.context_management.strategies.summary_builder.get_artifact_tracker")
    def test_artifact_tracker_integration(self, mock_tracker_fn: MagicMock) -> None:
        mock_tracker = MagicMock()
        mock_tracker.get_summary.return_value = "artifact index content"
        mock_tracker_fn.return_value = mock_tracker

        summary = StructuredSummary(user_goal="test")
        msg = create_summary_message(summary, chat_id="chat123")
        assert "artifact index content" in msg.content

    def test_limits_completed_actions(self) -> None:
        summary = StructuredSummary(user_goal="test", completed_actions=[f"action{i}" for i in range(20)])
        msg = create_summary_message(summary)
        content = msg.content
        json_start = content.index("<!-- SUMMARY_JSON")
        text_part = content[:json_start]
        assert "action9" in text_part
        assert "action10" not in text_part

    def test_limits_key_findings(self) -> None:
        summary = StructuredSummary(user_goal="test", key_findings=[f"finding{i}" for i in range(10)])
        msg = create_summary_message(summary)
        content = msg.content
        json_start = content.index("<!-- SUMMARY_JSON")
        text_part = content[:json_start]
        assert "finding4" in text_part
        assert "finding5" not in text_part

    def test_errors_and_fixes_section(self) -> None:
        summary = StructuredSummary(
            user_goal="fix bugs",
            errors_and_fixes=["ImportError -> added missing import", "timeout -> increased deadline"],
        )
        msg = create_summary_message(summary)
        content = msg.content
        assert "Errors & Fixes:" in content
        assert "ImportError -> added missing import" in content
        assert "timeout -> increased deadline" in content

    def test_errors_and_fixes_after_findings(self) -> None:
        summary = StructuredSummary(
            user_goal="Goal",
            completed_actions=["action1"],
            errors_and_fixes=["error -> fix"],
            key_findings=["finding1"],
        )
        msg = create_summary_message(summary)
        content = msg.content
        action_pos = content.index("action1")
        finding_pos = content.index("finding1")
        error_pos = content.index("error -> fix")
        assert action_pos < finding_pos < error_pos

    def test_errors_and_fixes_limited_to_8(self) -> None:
        summary = StructuredSummary(user_goal="test", errors_and_fixes=[f"err{i} -> fix{i}" for i in range(15)])
        msg = create_summary_message(summary)
        content = msg.content
        json_start = content.index("<!-- SUMMARY_JSON")
        text_part = content[:json_start]
        assert "err7 -> fix7" in text_part
        assert "err8 -> fix8" not in text_part

    def test_empty_errors_and_fixes_no_section(self) -> None:
        summary = StructuredSummary(user_goal="test", errors_and_fixes=[])
        msg = create_summary_message(summary)
        assert "Errors & Fixes" not in msg.content

    def test_errors_and_fixes_in_json_block(self) -> None:
        summary = StructuredSummary(user_goal="test", errors_and_fixes=["crash -> null check"])
        msg = create_summary_message(summary)
        assert '"errors_and_fixes"' in msg.content
        assert "crash -> null check" in msg.content

    def test_handoff_preamble_present(self) -> None:
        summary = StructuredSummary(user_goal="test goal")
        msg = create_summary_message(summary)
        assert "Do NOT answer questions mentioned in the summary" in msg.content
        assert "active_task" in msg.content

    def test_active_task_rendered(self) -> None:
        summary = StructuredSummary(user_goal="test", active_task="重构 auth 模块")
        msg = create_summary_message(summary)
        assert "Active Task: 重构 auth 模块" in msg.content

    def test_active_task_none_not_rendered(self) -> None:
        summary = StructuredSummary(user_goal="test", active_task="None")
        msg = create_summary_message(summary)
        assert "Active Task" not in msg.content

    def test_constraints_rendered(self) -> None:
        summary = StructuredSummary(user_goal="test", constraints_and_preferences=["使用TypeScript", "不要创建新文件"])
        msg = create_summary_message(summary)
        assert "User Constraints & Preferences:" in msg.content
        assert "使用TypeScript" in msg.content
        assert "不要创建新文件" in msg.content

    def test_resolved_questions_rendered(self) -> None:
        summary = StructuredSummary(user_goal="test", resolved_questions=["如何安装 -> pip install x"])
        msg = create_summary_message(summary)
        assert "Resolved Questions:" in msg.content
        assert "如何安装 -> pip install x" in msg.content

    def test_pending_user_asks_rendered(self) -> None:
        summary = StructuredSummary(user_goal="test", pending_user_asks=["添加测试"])
        msg = create_summary_message(summary)
        assert "Pending User Asks:" in msg.content
        assert "添加测试" in msg.content

    def test_pending_user_asks_none_filtered(self) -> None:
        summary = StructuredSummary(user_goal="test", pending_user_asks=["None"])
        msg = create_summary_message(summary)
        assert "Pending User Asks" not in msg.content

    def test_active_state_rendered(self) -> None:
        summary = StructuredSummary(user_goal="test", active_state="main分支, 50/52测试通过")
        msg = create_summary_message(summary)
        assert "Working State: main分支, 50/52测试通过" in msg.content

    def test_lost_in_middle_new_fields_ordering(self) -> None:
        """Verify active_task/constraints are in the head and pending/state in the tail."""
        summary = StructuredSummary(
            user_goal="Goal",
            active_task="重构模块",
            constraints_and_preferences=["约束1"],
            completed_actions=["操作1"],
            resolved_questions=["Q -> A"],
            key_findings=["发现1"],
            pending_user_asks=["待办1"],
            active_state="dev分支",
        )
        msg = create_summary_message(summary)
        content = msg.content
        task_pos = content.index("重构模块")
        constraint_pos = content.index("约束1")
        actions_pos = content.index("操作1")
        resolved_pos = content.index("Q -> A")
        finding_pos = content.index("发现1")
        pending_pos = content.index("待办1")
        state_pos = content.index("dev分支")
        # Head: task, constraints before actions
        assert task_pos < actions_pos
        assert constraint_pos < actions_pos
        # Middle: actions, resolved
        assert actions_pos < resolved_pos
        # Tail: findings, pending, state after resolved
        assert resolved_pos < finding_pos
        assert finding_pos < pending_pos
        assert pending_pos < state_pos


class TestExtractProtectedHead:
    def test_extract_system_and_first_turn(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.summary_builder import extract_protected_head

        messages = [
            SystemMessage(content="sys1"),
            SystemMessage(content="sys2"),
            HumanMessage(content="h1"),
            AIMessage(content="a1"),
            HumanMessage(content="h2"),
            AIMessage(content="a2"),
        ]
        head = extract_protected_head(messages)
        assert len(head) == 4
        assert isinstance(head[0], SystemMessage)
        assert isinstance(head[1], SystemMessage)
        assert isinstance(head[2], HumanMessage)
        assert isinstance(head[3], AIMessage)

    def test_extract_only_systems(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.summary_builder import extract_protected_head

        messages = [
            SystemMessage(content="sys1"),
            AIMessage(content="a1"),  # No HumanMessage right after system
        ]
        head = extract_protected_head(messages)
        assert len(head) == 1
        assert isinstance(head[0], SystemMessage)

    def test_extract_no_system(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.summary_builder import extract_protected_head

        messages = [
            HumanMessage(content="h1"),
            AIMessage(content="a1"),
            HumanMessage(content="h2"),
        ]
        head = extract_protected_head(messages)
        assert len(head) == 2
        assert isinstance(head[0], HumanMessage)
        assert isinstance(head[1], AIMessage)

    def test_extract_empty(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.summary_builder import extract_protected_head

        assert extract_protected_head([]) == []
