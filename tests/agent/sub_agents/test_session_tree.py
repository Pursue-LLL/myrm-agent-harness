"""Tests for session_tree registry merge helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

from myrm_agent_harness.agent.sub_agents.manager import (
    ACTIVE_SUBAGENT_SESSIONS,
    ACTIVE_SUBAGENTS,
    SubagentManager,
)
from myrm_agent_harness.agent.sub_agents.session_tree import (
    list_active_children_from_registry,
    merge_active_subagent_children,
)


def test_list_active_children_from_registry_filters_by_session() -> None:
    session_a = "chat-a"
    session_b = "chat-b"

    manager_a = MagicMock(spec=SubagentManager)
    manager_a._parent_agent = MagicMock(session_id=session_a)
    manager_a.list_children.return_value = [
        {"task_id": "task-1", "status": "running", "agent_type": "bash_worker"},
    ]

    manager_b = MagicMock(spec=SubagentManager)
    manager_b._parent_agent = MagicMock(session_id=session_b)
    manager_b.list_children.return_value = [
        {"task_id": "task-2", "status": "running", "agent_type": "researcher"},
    ]

    ACTIVE_SUBAGENTS["task-1"] = manager_a
    ACTIVE_SUBAGENTS["task-2"] = manager_b
    try:
        rows = list_active_children_from_registry(session_a)
        assert len(rows) == 1
        assert rows[0]["task_id"] == "task-1"
    finally:
        ACTIVE_SUBAGENTS.pop("task-1", None)
        ACTIVE_SUBAGENTS.pop("task-2", None)


def test_merge_active_subagent_children_dedupes_gateway_and_registry() -> None:
    session_id = "chat-merge"
    manager = MagicMock(spec=SubagentManager)
    manager._parent_agent = MagicMock(session_id=session_id)
    manager.list_children.return_value = [
        {"task_id": "live", "status": "running", "progress": 99},
    ]
    ACTIVE_SUBAGENTS["live"] = manager
    try:
        gateway_rows = [{"task_id": "live", "status": "running", "progress": 10}]
        merged = merge_active_subagent_children(session_id, gateway_rows)
        assert len(merged) == 1
        assert merged[0]["task_id"] == "live"
        assert merged[0]["progress"] == 10
    finally:
        ACTIVE_SUBAGENTS.pop("live", None)


def test_list_active_children_from_registry_uses_spawn_session_map() -> None:
    chat_uuid = "map-789"
    session_id = f"chat_{chat_uuid}"
    manager = MagicMock(spec=SubagentManager)
    manager._parent_agent = MagicMock(session_id=None, _last_context={})
    manager.list_children.return_value = [
        {"task_id": "task-map", "status": "running", "agent_type": "bash_worker"},
    ]
    ACTIVE_SUBAGENTS["task-map"] = manager
    ACTIVE_SUBAGENT_SESSIONS["task-map"] = session_id
    try:
        rows = list_active_children_from_registry(chat_uuid)
        assert len(rows) == 1
        assert rows[0]["task_id"] == "task-map"
    finally:
        ACTIVE_SUBAGENTS.pop("task-map", None)
        ACTIVE_SUBAGENT_SESSIONS.pop("task-map", None)


def test_list_active_children_from_registry_reads_last_context_session_id() -> None:
    chat_uuid = "ctx-456"
    parent = MagicMock()
    parent.session_id = None
    parent._last_context = {"session_id": f"chat_{chat_uuid}"}
    manager = MagicMock(spec=SubagentManager)
    manager._parent_agent = parent
    manager.list_children.return_value = [
        {"task_id": "task-ctx", "status": "running", "agent_type": "bash_worker"},
    ]
    ACTIVE_SUBAGENTS["task-ctx"] = manager
    try:
        rows = list_active_children_from_registry(chat_uuid)
        assert len(rows) == 1
        assert rows[0]["task_id"] == "task-ctx"
    finally:
        ACTIVE_SUBAGENTS.pop("task-ctx", None)


def test_list_active_children_from_registry_accepts_chat_prefix() -> None:
    chat_uuid = "abc-123"
    manager = MagicMock(spec=SubagentManager)
    manager._parent_agent = MagicMock(session_id=f"chat_{chat_uuid}")
    manager.list_children.return_value = [
        {"task_id": "task-prefixed", "status": "running", "agent_type": "bash_worker"},
    ]
    ACTIVE_SUBAGENTS["task-prefixed"] = manager
    try:
        rows = list_active_children_from_registry(chat_uuid)
        assert len(rows) == 1
        assert rows[0]["task_id"] == "task-prefixed"
    finally:
        ACTIVE_SUBAGENTS.pop("task-prefixed", None)


def test_merge_active_subagent_children_registry_when_gateway_empty() -> None:
    session_id = "chat-registry-only"
    manager = MagicMock(spec=SubagentManager)
    manager._parent_agent = MagicMock(session_id=session_id)
    manager.list_children.return_value = [
        {"task_id": "bg-1", "status": "running", "agent_type": "bash_worker"},
    ]
    ACTIVE_SUBAGENTS["bg-1"] = manager
    try:
        merged = merge_active_subagent_children(session_id, [])
        assert len(merged) == 1
        assert merged[0]["task_id"] == "bg-1"
    finally:
        ACTIVE_SUBAGENTS.pop("bg-1", None)
