"""Tests for sub_agents/notifications.py."""

from __future__ import annotations

import time

from myrm_agent_harness.agent.sub_agents.notifications import (
    _NOTIFICATION_TTL_SECONDS,
    NotificationManager,
    SubagentNotification,
    format_active_subagent_context,
    format_notification,
)
from myrm_agent_harness.agent.sub_agents.types import (
    AgentHandoverState,
    SubAgentResult,
    SubAgentStatus,
)


class TestSubagentNotification:
    def test_frozen_dataclass(self):
        n = SubagentNotification(content="hello", timestamp=1.0)
        assert n.content == "hello"
        assert n.timestamp == 1.0

    def test_ttl_constant(self):
        assert _NOTIFICATION_TTL_SECONDS == 300.0


class TestFormatNotification:
    def test_success_with_result(self):
        result = SubAgentResult(
            success=True,
            task_id="t1",
            agent_type="worker",
            result="all good",
            completed_at=time.time(),
            status=SubAgentStatus.COMPLETED,
            duration_seconds=2.5,
        )
        text = format_notification(result)
        assert "completed successfully" in text
        assert "worker" in text
        assert "t1" in text
        assert "2.5s" in text
        assert "all good" in text
        assert "Process this result" in text

    def test_failure_with_error(self):
        result = SubAgentResult(
            success=False,
            task_id="t2",
            agent_type="researcher",
            error="timeout",
            completed_at=time.time(),
            status=SubAgentStatus.FAILED,
        )
        text = format_notification(result)
        assert "failed" in text
        assert "timeout" in text
        assert "researcher" in text

    def test_success_no_result(self):
        result = SubAgentResult(
            success=True, task_id="t3", agent_type="checker", completed_at=time.time(), status=SubAgentStatus.COMPLETED
        )
        text = format_notification(result)
        assert "completed successfully" in text
        assert "Result:" not in text

    def test_no_duration(self):
        result = SubAgentResult(
            success=True,
            task_id="t4",
            agent_type="w",
            result="ok",
            completed_at=time.time(),
            status=SubAgentStatus.COMPLETED,
        )
        text = format_notification(result)
        assert "s)" not in text

    def test_handover_with_all_fields(self):
        result = SubAgentResult(
            success=True,
            task_id="t5",
            agent_type="researcher",
            result="done",
            completed_at=time.time(),
            status=SubAgentStatus.COMPLETED,
            handover_state=AgentHandoverState(
                task_completed=["analysis A", "analysis B"],
                pending_todos=["analysis C"],
                risks_or_notes=["data may be stale"],
            ),
        )
        text = format_notification(result)
        assert "Handover:" in text
        assert "Completed:" in text
        assert " - analysis A" in text
        assert " - analysis B" in text
        assert "Pending:" in text
        assert " - analysis C" in text
        assert "Risks:" in text
        assert " - data may be stale" in text

    def test_handover_with_completed_only(self):
        result = SubAgentResult(
            success=True,
            task_id="t6",
            agent_type="worker",
            result="ok",
            completed_at=time.time(),
            status=SubAgentStatus.COMPLETED,
            handover_state=AgentHandoverState(task_completed=["step 1"]),
        )
        text = format_notification(result)
        assert "Completed:" in text
        assert " - step 1" in text
        assert "Pending:" not in text
        assert "Risks:" not in text

    def test_handover_with_empty_state(self):
        result = SubAgentResult(
            success=True,
            task_id="t7",
            agent_type="worker",
            result="ok",
            completed_at=time.time(),
            status=SubAgentStatus.COMPLETED,
            handover_state=AgentHandoverState(),
        )
        text = format_notification(result)
        assert "Handover:" not in text

    def test_no_handover_state(self):
        result = SubAgentResult(
            success=True,
            task_id="t8",
            agent_type="worker",
            result="ok",
            completed_at=time.time(),
            status=SubAgentStatus.COMPLETED,
        )
        text = format_notification(result)
        assert "Handover:" not in text


class TestFormatActiveSubagentContext:
    def test_no_running_returns_none(self):
        children: list[dict[str, object]] = [
            {"task_id": "t1", "agent_type": "worker", "status": "completed", "done": True},
        ]
        assert format_active_subagent_context(children) is None

    def test_empty_list_returns_none(self):
        assert format_active_subagent_context([]) is None

    def test_single_running_child(self):
        children: list[dict[str, object]] = [
            {"task_id": "abc", "agent_type": "searcher", "status": "running", "done": False, "description": "find docs"},
        ]
        result = format_active_subagent_context(children)
        assert result is not None
        assert "[Active subagents]" in result
        assert "searcher" in result
        assert "abc" in result
        assert "find docs" in result
        assert "Do NOT spawn duplicate" in result

    def test_multiple_running_children(self):
        children: list[dict[str, object]] = [
            {"task_id": "t1", "agent_type": "searcher", "status": "running", "done": False},
            {"task_id": "t2", "agent_type": "analyst", "status": "running", "done": False},
            {"task_id": "t3", "agent_type": "writer", "status": "completed", "done": True},
        ]
        result = format_active_subagent_context(children)
        assert result is not None
        assert "searcher" in result
        assert "analyst" in result
        assert "writer" not in result

    def test_done_true_excluded(self):
        children: list[dict[str, object]] = [
            {"task_id": "t1", "agent_type": "worker", "status": "running", "done": True},
        ]
        assert format_active_subagent_context(children) is None

    def test_no_description(self):
        children: list[dict[str, object]] = [
            {"task_id": "t1", "agent_type": "coder", "status": "running", "done": False},
        ]
        result = format_active_subagent_context(children)
        assert result is not None
        assert "coder (task_id=t1)" in result
        assert ": " not in result.split("\n")[1]

    def test_missing_task_id_defaults_to_question_mark(self):
        children: list[dict[str, object]] = [
            {"agent_type": "worker", "status": "running", "done": False},
        ]
        result = format_active_subagent_context(children)
        assert result is not None
        assert "task_id=?" in result

    def test_missing_agent_type_defaults_to_unknown(self):
        children: list[dict[str, object]] = [
            {"task_id": "t1", "status": "running", "done": False},
        ]
        result = format_active_subagent_context(children)
        assert result is not None
        assert "unknown (task_id=t1)" in result

    def test_description_none_treated_as_empty(self):
        children: list[dict[str, object]] = [
            {"task_id": "t1", "agent_type": "worker", "status": "running", "done": False, "description": None},
        ]
        result = format_active_subagent_context(children)
        assert result is not None
        assert "worker (task_id=t1)" in result

    def test_all_completed_returns_none(self):
        children: list[dict[str, object]] = [
            {"task_id": "t1", "agent_type": "a", "status": "completed", "done": True},
            {"task_id": "t2", "agent_type": "b", "status": "failed", "done": True},
            {"task_id": "t3", "agent_type": "c", "status": "cancelled", "done": True},
        ]
        assert format_active_subagent_context(children) is None


class TestNotificationManager:
    def test_init(self):
        mgr = NotificationManager()
        assert mgr._pending_notifications is not None
        assert len(mgr._pending_notifications) == 0

    def test_add_and_drain(self):
        mgr = NotificationManager()
        result = SubAgentResult(
            success=True, task_id="t1", agent_type="w", result="ok",
            completed_at=time.time(), status=SubAgentStatus.COMPLETED,
        )
        mgr.add_notification(result, timestamp=time.time())
        assert len(mgr._pending_notifications) == 1

        merged = mgr.drain_notifications()
        assert merged is not None
        assert "ok" in merged
        assert len(mgr._pending_notifications) == 0

    def test_drain_empty_returns_none(self):
        mgr = NotificationManager()
        assert mgr.drain_notifications() is None

    def test_drain_expired_returns_none(self):
        mgr = NotificationManager()
        result = SubAgentResult(
            success=True, task_id="t1", agent_type="w", result="ok",
            completed_at=time.time(), status=SubAgentStatus.COMPLETED,
        )
        old_timestamp = time.time() - _NOTIFICATION_TTL_SECONDS - 1
        mgr.add_notification(result, timestamp=old_timestamp)
        assert mgr.drain_notifications() is None

    def test_drain_merges_multiple(self):
        mgr = NotificationManager()
        now = time.time()
        for i in range(3):
            result = SubAgentResult(
                success=True, task_id=f"t{i}", agent_type="w", result=f"r{i}",
                completed_at=now, status=SubAgentStatus.COMPLETED,
            )
            mgr.add_notification(result, timestamp=now)
        merged = mgr.drain_notifications()
        assert merged is not None
        assert "r0" in merged
        assert "r1" in merged
        assert "r2" in merged
        assert "---" in merged
