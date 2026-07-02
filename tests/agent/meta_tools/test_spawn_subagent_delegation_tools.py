"""Unit tests for spawn_subagent delegation tool factories (parallel + teammate)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.sub_agents.types import DELEGATION_CAPABILITY_MANIFEST


def _make_parent() -> MagicMock:
    parent = MagicMock()
    parent.config = None
    parent.engine_params = {}
    parent.list_children.return_value = []
    return parent


class CatalogStub:
    async def list_available(self) -> list[str]:
        return ["worker"]

    async def resolve(self, agent_type: str) -> object | None:
        return None


class TestDelegateParallelTasksTool:
    def test_factory_name(self) -> None:
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch import (
            create_delegate_parallel_tasks_tool,
        )

        parent = _make_parent()
        catalog = CatalogStub()
        tool = create_delegate_parallel_tasks_tool(parent, lambda: [], catalog)
        assert tool.name == "delegate_parallel_tasks_tool"

    def test_empty_tasks_returns_error(self) -> None:
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch import (
            create_delegate_parallel_tasks_tool,
        )

        parent = _make_parent()
        catalog = CatalogStub()
        tool = create_delegate_parallel_tasks_tool(parent, lambda: [], catalog)
        result = tool.func(tasks=[])
        assert result["success"] is False
        assert "No tasks" in result["error"]

    def test_interrupt_payload_and_resume(self) -> None:
        from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_batch import (
            TaskRequest,
            create_delegate_parallel_tasks_tool,
        )

        parent = _make_parent()
        catalog = CatalogStub()
        tool = create_delegate_parallel_tasks_tool(parent, lambda: [], catalog)
        tasks = [
            TaskRequest(agent_type="worker", objective="research topic A"),
            TaskRequest(agent_type="worker", objective="research topic B"),
        ]
        fake_decisions = [{"task_id": "t1", "success": True}]

        with patch(
            "langgraph.types.interrupt",
            return_value=fake_decisions,
        ) as interrupt_mock:
            result = tool.func(tasks=tasks)

        interrupt_mock.assert_called_once()
        payload = interrupt_mock.call_args.args[0]
        assert payload["action_type"] == "swarm_fission"
        assert len(payload["tasks"]) == 2
        assert result["success"] is True
        assert result["results"] == fake_decisions


class TestSendTeammateMessageTool:
    @pytest.mark.asyncio
    async def test_rejects_outside_subagent_context(self) -> None:
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.send_teammate_tool import (
            create_send_teammate_message_tool,
        )

        parent = _make_parent()
        tool = create_send_teammate_message_tool(parent)
        with patch(
            "myrm_agent_harness.agent.meta_tools.spawn_subagent.send_teammate_tool.get_subagent_task_id",
            return_value=None,
        ):
            result = await tool.ainvoke({"target_task_id": "peer-1", "body": "hello"})
        assert result["success"] is False
        assert "subagent context" in result["error"]

    @pytest.mark.asyncio
    async def test_send_success_via_mailbox(self) -> None:
        from myrm_agent_harness.agent.coordination.types import TeammateMessage
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.send_teammate_tool import (
            create_send_teammate_message_tool,
        )

        parent = _make_parent()
        parent.list_children.return_value = [{"task_id": "self-1", "agent_type": "coder"}]
        tool = create_send_teammate_message_tool(parent)

        mailbox = MagicMock()
        mailbox.send = AsyncMock(
            return_value=MagicMock(accepted=True, error=None, message_id="msg-1"),
        )
        mailbox.list_active_roster.return_value = [{"task_id": "peer-2", "agent_type": "researcher"}]

        with (
            patch(
                "myrm_agent_harness.agent.meta_tools.spawn_subagent.send_teammate_tool.get_subagent_task_id",
                return_value="self-1",
            ),
            patch(
                "myrm_agent_harness.agent.meta_tools.spawn_subagent.send_teammate_tool.get_approval_session",
                return_value="sess-1",
            ),
            patch(
                "myrm_agent_harness.agent.meta_tools.spawn_subagent.send_teammate_tool.get_workspace_root",
                return_value="/tmp/ws",
            ),
            patch(
                "myrm_agent_harness.agent.meta_tools.spawn_subagent.send_teammate_tool.get_teammate_mailbox",
                new=AsyncMock(return_value=mailbox),
            ),
            patch(
                "myrm_agent_harness.agent.meta_tools.spawn_subagent.send_teammate_tool.emit_teammate_message_sse",
                new=AsyncMock(),
            ) as emit_sse,
        ):
            result = await tool.ainvoke({"target_task_id": "peer-2", "body": "status update"})

        assert result["success"] is True
        mailbox.send.assert_awaited_once()
        sent: TeammateMessage = mailbox.send.await_args.args[0]
        assert sent.from_task_id == "self-1"
        assert sent.to_task_id == "peer-2"
        assert sent.body == "status update"
        emit_sse.assert_awaited_once()


class TestAgentManageToolsFactory:
    @pytest.mark.asyncio
    async def test_cancel_subagent_not_found(self) -> None:
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.agent_manage_tool import (
            create_cancel_subagent_tool,
        )

        parent = _make_parent()
        parent.cancel_child.return_value = False
        tool = create_cancel_subagent_tool(parent)
        result = await tool.ainvoke({"task_id": "missing"})
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_steer_subagent_success_and_failure(self) -> None:
        from myrm_agent_harness.agent.meta_tools.spawn_subagent.agent_manage_tool import (
            create_steer_subagent_tool,
        )

        parent = _make_parent()
        tool = create_steer_subagent_tool(parent)

        parent.steer_child.return_value = True
        ok = await tool.ainvoke({"task_id": "run-1", "message": "focus on API docs"})
        assert ok["success"] is True

        parent.steer_child.return_value = False
        fail = await tool.ainvoke({"task_id": "gone-1", "message": "too late"})
        assert fail["success"] is False


class TestDelegationCapabilityManifest:
    def test_orchestrator_child_tools_include_all_seven(self) -> None:
        names = DELEGATION_CAPABILITY_MANIFEST.orchestrator_child_tools
        assert "delegate_task_tool" in names
        assert "batch_delegate_tasks_tool" in names
        assert "delegate_parallel_tasks_tool" in names
        assert "list_subagents_tool" in names
        assert "cancel_subagent_tool" in names
        assert "steer_subagent_tool" in names
        assert "send_teammate_message_tool" in names
        assert len(names) == 7
