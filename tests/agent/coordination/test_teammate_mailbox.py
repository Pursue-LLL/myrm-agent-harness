"""Tests for teammate P2P mailbox."""

from __future__ import annotations

from collections import deque
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.coordination.mailbox import (
    _RATE_LIMIT_WINDOW_SEC,
    TeammateMailbox,
    drain_teammate_messages_for_task,
    emit_teammate_message_sse,
    format_roster_prompt,
    format_teammate_injection,
    get_teammate_mailbox,
    group_history_by_task,
    list_teammate_history,
)
from myrm_agent_harness.agent.coordination.types import TeammateMessage


@pytest.mark.asyncio
async def test_send_and_drain_unread() -> None:
    mailbox = TeammateMailbox("sess-test", workspace_path=None)

    msg = TeammateMessage(
        message_id="m1",
        session_id="sess-test",
        from_task_id="worker-a",
        to_task_id="worker-b",
        from_agent_type="researcher",
        body="API ready at /api/bar",
        created_at=1.0,
    )
    mailbox._inboxes.setdefault("worker-b", deque()).append(msg)

    result = mailbox.drain_unread_sync("worker-b")
    assert len(result.messages) == 1
    assert result.messages[0].body == "API ready at /api/bar"
    assert mailbox.drain_unread_sync("worker-b").messages == []

    injection = format_teammate_injection(result.messages)
    assert injection is not None
    assert "<teammate-message>" in injection
    assert "worker-a" in injection


@pytest.mark.asyncio
async def test_get_teammate_mailbox_singleton() -> None:
    m1 = await get_teammate_mailbox("sess-1", None)
    m2 = await get_teammate_mailbox("sess-1", None)
    assert m1 is m2


def test_rate_limit_blocks_spam_within_window() -> None:
    mailbox = TeammateMailbox("sess-rate", workspace_path=None)
    sender = "sender-a"
    base = 1_000_000.0
    with patch("myrm_agent_harness.agent.coordination.mailbox.time.time", return_value=base):
        for _ in range(30):
            assert mailbox._check_rate_limit(sender) is True
        assert mailbox._check_rate_limit(sender) is False


def test_send_returns_rate_limit_error() -> None:
    mailbox = TeammateMailbox("sess-rate-err", workspace_path=None)
    msg = TeammateMessage(
        message_id="m-rate",
        session_id="sess-rate-err",
        from_task_id="sender-a",
        to_task_id="worker-b",
        from_agent_type="coder",
        body="x",
        created_at=1.0,
    )
    with patch("myrm_agent_harness.agent.coordination.mailbox.time.time", return_value=100.0):
        for _ in range(30):
            assert mailbox.send_sync(msg).accepted is True
        blocked = mailbox.send_sync(msg)
    assert blocked.accepted is False
    assert blocked.error is not None
    assert "rate limit" in blocked.error.lower()


def test_rate_limit_sliding_window_allows_after_expiry() -> None:
    mailbox = TeammateMailbox("sess-rate-slide", workspace_path=None)
    sender = "sender-b"
    times = iter([100.0 + i for i in range(30)])

    def fake_time() -> float:
        return next(times, 100.0 + _RATE_LIMIT_WINDOW_SEC + 1)

    with patch("myrm_agent_harness.agent.coordination.mailbox.time.time", side_effect=fake_time):
        for _ in range(30):
            assert mailbox._check_rate_limit(sender) is True
        assert mailbox._check_rate_limit(sender) is True


def test_group_history_by_task() -> None:
    history = [
        {
            "message_id": "a",
            "from_task_id": "t1",
            "to_task_id": "t2",
            "body": "hi",
            "created_at": 1.0,
        }
    ]
    grouped = group_history_by_task(history)
    assert "t1" in grouped
    assert "t2" in grouped
    assert len(grouped["t1"]) == 1
    duplicate = [*history, dict(history[0])]
    grouped_dup = group_history_by_task(duplicate)
    assert len(grouped_dup["t1"]) == 1


def test_list_teammate_history_empty_without_mailbox() -> None:
    assert list_teammate_history("unknown-session", None) == []


@pytest.mark.asyncio
async def test_unregister_active_teammate() -> None:
    from myrm_agent_harness.agent.coordination.mailbox import (
        register_active_teammate,
        unregister_active_teammate,
    )

    await register_active_teammate("sess-unreg", None, "worker-a", "coder")
    mailbox = await get_teammate_mailbox("sess-unreg", None)
    assert mailbox.list_active_roster()
    unregister_active_teammate("sess-unreg", "worker-a")
    assert mailbox.list_active_roster() == []


@pytest.mark.asyncio
async def test_register_and_send_teammate_message() -> None:
    from myrm_agent_harness.agent.coordination.mailbox import register_active_teammate

    await register_active_teammate("sess-roster", None, "worker-a", "coder")
    await register_active_teammate("sess-roster", None, "worker-b", "researcher")
    mailbox = await get_teammate_mailbox("sess-roster", None)
    msg = TeammateMessage(
        message_id="m-send-1",
        session_id="sess-roster",
        from_task_id="worker-a",
        to_task_id="worker-b",
        from_agent_type="coder",
        body="handoff payload",
        created_at=1.0,
    )
    result = await mailbox.send(msg)
    assert result.accepted is True
    assert result.error is None
    drained = mailbox.drain_unread_sync("worker-b")
    assert drained.messages[0].body == "handoff payload"


@pytest.mark.asyncio
async def test_emit_teammate_message_sse_uses_progress_sink() -> None:
    msg = TeammateMessage(
        message_id="m-sse-1",
        session_id="sess-sse",
        from_task_id="worker-a",
        to_task_id="worker-b",
        from_agent_type="coder",
        body="live update",
        created_at=1.0,
    )
    sink = MagicMock()
    sink.emit = AsyncMock()
    with patch(
        "myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink",
        return_value=sink,
    ):
        await emit_teammate_message_sse(msg)
    sink.emit.assert_awaited_once()
    event = sink.emit.await_args.args[0]
    assert event["type"] == "teammate_message"
    assert event["data"]["body"] == "live update"
    assert event["data"]["chat_id"] == "sess-sse"


def test_jsonl_trim_keeps_tail(tmp_path: Path) -> None:
    from myrm_agent_harness.agent.coordination.mailbox import _MAX_JSONL_LINES

    workspace = str(tmp_path)
    mailbox = TeammateMailbox("sess-trim", workspace_path=workspace)
    msg = TeammateMessage(
        message_id="m-trim",
        session_id="sess-trim",
        from_task_id="a",
        to_task_id="b",
        from_agent_type="coder",
        body="line",
        created_at=1.0,
    )
    path = tmp_path / "teammate_mailbox_sess-trim.jsonl"
    path.write_text("\n".join('{"message_id":"x"}' for _ in range(_MAX_JSONL_LINES + 50)) + "\n")
    mailbox._persist(msg)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) <= _MAX_JSONL_LINES


# ── Roster injection tests ──────────────────────────────────────────────


def test_format_roster_prompt_returns_xml_for_non_empty() -> None:
    roster = [
        {"task_id": "task_001", "agent_type": "researcher"},
        {"task_id": "task_002", "agent_type": "coder"},
    ]
    result = format_roster_prompt(roster)
    assert result is not None
    assert "<active_teammates>" in result
    assert "task_001: researcher" in result
    assert "task_002: coder" in result
    assert "</active_teammates>" in result


def test_format_roster_prompt_returns_none_for_empty() -> None:
    assert format_roster_prompt([]) is None


@pytest.mark.asyncio
async def test_drain_with_include_roster_injects_roster() -> None:
    """drain_teammate_messages_for_task with include_roster=True appends roster."""
    from myrm_agent_harness.agent.coordination.mailbox import (
        _MAILBOX_CACHE,
        register_active_teammate,
    )

    sid = "sess-roster-inject"
    await register_active_teammate(sid, None, "worker-a", "coder")
    await register_active_teammate(sid, None, "worker-b", "researcher")

    result = drain_teammate_messages_for_task(sid, "worker-a", include_roster=True)
    assert result is not None
    assert "<active_teammates>" in result
    assert "worker-b: researcher" in result
    assert "worker-a" not in result.split("<active_teammates>")[1]

    _MAILBOX_CACHE.pop(sid, None)


@pytest.mark.asyncio
async def test_drain_without_roster_flag_excludes_roster() -> None:
    """Default drain (include_roster=False) does not inject roster."""
    from myrm_agent_harness.agent.coordination.mailbox import (
        _MAILBOX_CACHE,
        register_active_teammate,
    )

    sid = "sess-no-roster"
    await register_active_teammate(sid, None, "worker-a", "coder")
    await register_active_teammate(sid, None, "worker-b", "researcher")

    result = drain_teammate_messages_for_task(sid, "worker-a", include_roster=False)
    assert result is None

    _MAILBOX_CACHE.pop(sid, None)


@pytest.mark.asyncio
async def test_drain_with_messages_and_roster() -> None:
    """Both messages and roster are included when both exist."""
    from myrm_agent_harness.agent.coordination.mailbox import (
        _MAILBOX_CACHE,
        register_active_teammate,
    )

    sid = "sess-both"
    await register_active_teammate(sid, None, "worker-a", "coder")
    await register_active_teammate(sid, None, "worker-b", "researcher")

    mailbox = await get_teammate_mailbox(sid, None)
    msg = TeammateMessage(
        message_id="m-both-1",
        session_id=sid,
        from_task_id="worker-b",
        to_task_id="worker-a",
        from_agent_type="researcher",
        body="found a lead",
        created_at=1.0,
    )
    mailbox.send_sync(msg)

    result = drain_teammate_messages_for_task(sid, "worker-a", include_roster=True)
    assert result is not None
    assert "<teammate-message>" in result
    assert "found a lead" in result
    assert "<active_teammates>" in result
    assert "worker-b: researcher" in result

    _MAILBOX_CACHE.pop(sid, None)


def test_drain_returns_none_for_unknown_session() -> None:
    result = drain_teammate_messages_for_task("unknown-sid", "unknown-task")
    assert result is None


def test_drain_returns_none_for_empty_ids() -> None:
    assert drain_teammate_messages_for_task("", "task-1") is None
    assert drain_teammate_messages_for_task("sess-1", "") is None


# ── Edge-case / boundary tests ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_roster_excludes_self_only_teammate() -> None:
    """When the only registered teammate is the drainer itself, roster is empty."""
    from myrm_agent_harness.agent.coordination.mailbox import (
        _MAILBOX_CACHE,
        register_active_teammate,
    )

    sid = "sess-self-only"
    await register_active_teammate(sid, None, "solo-agent", "coder")

    result = drain_teammate_messages_for_task(sid, "solo-agent", include_roster=True)
    assert result is None

    _MAILBOX_CACHE.pop(sid, None)


@pytest.mark.asyncio
async def test_roster_refreshes_after_teammate_join() -> None:
    """Roster reflects newly joined teammates after initial drain."""
    from myrm_agent_harness.agent.coordination.mailbox import (
        _MAILBOX_CACHE,
        register_active_teammate,
    )

    sid = "sess-dynamic-roster"
    await register_active_teammate(sid, None, "worker-a", "coder")

    r1 = drain_teammate_messages_for_task(sid, "worker-a", include_roster=True)
    assert r1 is None

    await register_active_teammate(sid, None, "worker-b", "researcher")
    r2 = drain_teammate_messages_for_task(sid, "worker-a", include_roster=True)
    assert r2 is not None
    assert "worker-b: researcher" in r2

    _MAILBOX_CACHE.pop(sid, None)


@pytest.mark.asyncio
async def test_roster_refreshes_after_teammate_leave() -> None:
    """Roster reflects teammate departure."""
    from myrm_agent_harness.agent.coordination.mailbox import (
        _MAILBOX_CACHE,
        register_active_teammate,
        unregister_active_teammate,
    )

    sid = "sess-leave-roster"
    await register_active_teammate(sid, None, "worker-a", "coder")
    await register_active_teammate(sid, None, "worker-b", "researcher")

    r1 = drain_teammate_messages_for_task(sid, "worker-a", include_roster=True)
    assert r1 is not None
    assert "worker-b" in r1

    unregister_active_teammate(sid, "worker-b")
    r2 = drain_teammate_messages_for_task(sid, "worker-a", include_roster=True)
    assert r2 is None

    _MAILBOX_CACHE.pop(sid, None)


@pytest.mark.asyncio
async def test_concurrent_drain_does_not_duplicate_messages() -> None:
    """Two sequential drains on the same task should not return duplicates."""
    from myrm_agent_harness.agent.coordination.mailbox import (
        _MAILBOX_CACHE,
        register_active_teammate,
    )

    sid = "sess-concurrent-drain"
    await register_active_teammate(sid, None, "worker-a", "coder")
    await register_active_teammate(sid, None, "worker-b", "researcher")

    mailbox = await get_teammate_mailbox(sid, None)
    msg = TeammateMessage(
        message_id="m-conc-1",
        session_id=sid,
        from_task_id="worker-b",
        to_task_id="worker-a",
        from_agent_type="researcher",
        body="important data",
        created_at=1.0,
    )
    mailbox.send_sync(msg)

    r1 = drain_teammate_messages_for_task(sid, "worker-a", include_roster=True)
    r2 = drain_teammate_messages_for_task(sid, "worker-a", include_roster=False)

    assert r1 is not None
    assert "important data" in r1
    assert r2 is None

    _MAILBOX_CACHE.pop(sid, None)


def test_many_teammates_roster_performance() -> None:
    """Roster with 50 teammates still renders correctly."""
    roster = [
        {"task_id": f"task_{i:03d}", "agent_type": f"type_{i % 5}"}
        for i in range(50)
    ]
    result = format_roster_prompt(roster)
    assert result is not None
    assert result.count("- task_") == 50
    assert "<active_teammates>" in result
    assert "</active_teammates>" in result
