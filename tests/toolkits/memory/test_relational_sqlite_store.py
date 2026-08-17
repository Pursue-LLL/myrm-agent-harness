"""SQLiteRelationalStore unit tests — Profile, Procedural, Pending, lifecycle."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.memory.protocols.relational import (
    RelationalStoreProtocol,
)
from myrm_agent_harness.toolkits.memory.relational import SQLiteRelationalStore
from myrm_agent_harness.toolkits.memory.relational.exceptions import (
    RelationalNotFoundError,
)
from myrm_agent_harness.toolkits.memory.types import (
    MemoryScope,
    MemoryStatus,
    MemoryType,
    PendingRecord,
    ProceduralMemory,
)


@pytest.fixture
async def store(tmp_path: Path) -> SQLiteRelationalStore:
    s = SQLiteRelationalStore(str(tmp_path / "test_rel.db"))
    yield s  # type: ignore[misc]
    await s.close()


# ── Protocol satisfaction ────────────────────────────────────────────


def test_satisfies_protocol(tmp_path: Path) -> None:
    s = SQLiteRelationalStore(str(tmp_path / "proto.db"))
    assert isinstance(s, RelationalStoreProtocol)


# ── Profile ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_and_get_profile(store: SQLiteRelationalStore) -> None:
    await store.set_profile("language", "zh")
    val = await store.get_profile("language")
    assert val == "zh"


@pytest.mark.asyncio
async def test_get_profile_not_found(store: SQLiteRelationalStore) -> None:
    val = await store.get_profile("nonexistent")
    assert val is None


@pytest.mark.asyncio
async def test_set_profile_upsert(store: SQLiteRelationalStore) -> None:
    await store.set_profile("lang", "en")
    await store.set_profile("lang", "zh")
    val = await store.get_profile("lang")
    assert val == "zh"


@pytest.mark.asyncio
async def test_delete_profile(store: SQLiteRelationalStore) -> None:
    await store.set_profile("k", "v")
    deleted = await store.delete_profile("k")
    assert deleted is True
    assert await store.get_profile("k") is None


@pytest.mark.asyncio
async def test_list_and_count_profiles(store: SQLiteRelationalStore) -> None:
    for i in range(5):
        await store.set_profile(f"key_{i}", f"val_{i}")
    profiles = await store.list_profiles()
    assert len(profiles) == 5
    count = await store.count_profiles()
    assert count == 5


@pytest.mark.asyncio
async def test_system_profiles_are_hidden_from_list_and_count(
    store: SQLiteRelationalStore,
) -> None:
    await store.set_profile("_system_internal_key", '{"data": 1}')
    await store.set_profile("language", "zh")

    profiles = await store.list_profiles()
    assert len(profiles) == 1
    assert profiles[0].key == "language"
    assert await store.count_profiles() == 1
    assert await store.get_profile("_system_internal_key") == '{"data": 1}'


@pytest.mark.asyncio
async def test_list_profiles_pagination(store: SQLiteRelationalStore) -> None:
    for i in range(10):
        await store.set_profile(f"k{i}", f"v{i}")
        page = await store.list_profiles(limit=3, offset=0)
    assert len(page) == 3


@pytest.mark.asyncio
async def test_profiles_are_isolated_by_namespace(store: SQLiteRelationalStore) -> None:
    await store.set_profile(
        "language",
        "zh",
        scope=MemoryScope(
            primary_namespace="channel:telegram",
            namespaces=["channel:telegram"],
            channel_id="telegram",
        ),
    )
    await store.set_profile(
        "language",
        "en",
        scope=MemoryScope(
            primary_namespace="channel:feishu",
            namespaces=["channel:feishu"],
            channel_id="feishu",
        ),
    )

    assert await store.get_profile("language", namespaces=["channel:telegram"]) == "zh"
    assert await store.get_profile("language", namespaces=["channel:feishu"]) == "en"
    profiles = await store.list_profiles(namespaces=["channel:telegram"])
    assert len(profiles) == 1
    assert profiles[0].scope.channel_id == "telegram"


# ── Procedural rules ────────────────────────────────────────────────


def _make_rule(trigger: str = "user asks", action: str = "respond") -> ProceduralMemory:
    return ProceduralMemory(
        content=f"When: {trigger} → Do: {action}",
        trigger=trigger,
        action=action,
        priority=1,
    )


@pytest.mark.asyncio
async def test_create_and_get_rule(store: SQLiteRelationalStore) -> None:
    rule = _make_rule()
    created = await store.create_rule(rule)
    assert created.id
    fetched = await store.get_rule(created.id)
    assert fetched is not None
    assert fetched.trigger == "user asks"


@pytest.mark.asyncio
async def test_get_rule_not_found(store: SQLiteRelationalStore) -> None:
    result = await store.get_rule("ghost")
    assert result is None


@pytest.mark.asyncio
async def test_search_rules(store: SQLiteRelationalStore) -> None:
    await store.create_rule(_make_rule("file request", "use Excel"))
    await store.create_rule(_make_rule("code review", "be strict"))
    results = await store.search_rules("file")
    assert len(results) == 1
    assert results[0].trigger == "file request"


@pytest.mark.asyncio
async def test_list_rules(store: SQLiteRelationalStore) -> None:
    await store.create_rule(_make_rule("a", "1"))
    await store.create_rule(_make_rule("b", "2"))
    rules = await store.list_rules()
    assert len(rules) == 2


@pytest.mark.asyncio
async def test_count_rules(store: SQLiteRelationalStore) -> None:
    await store.create_rule(_make_rule())
    assert await store.count_rules() == 1


@pytest.mark.asyncio
async def test_update_rule(store: SQLiteRelationalStore) -> None:
    created = await store.create_rule(_make_rule("old", "old_action"))
    updated_rule = _make_rule("new", "new_action")
    updated = await store.update_rule(created.id, updated_rule)
    assert updated.trigger == "new"
    fetched = await store.get_rule(created.id)
    assert fetched is not None
    assert fetched.action == "new_action"


@pytest.mark.asyncio
async def test_update_rule_not_found(store: SQLiteRelationalStore) -> None:
    with pytest.raises(RelationalNotFoundError):
        await store.update_rule("ghost", _make_rule())


@pytest.mark.asyncio
async def test_delete_rule(store: SQLiteRelationalStore) -> None:
    created = await store.create_rule(_make_rule())
    deleted = await store.delete_rule(created.id)
    assert deleted is True
    assert await store.get_rule(created.id) is None


@pytest.mark.asyncio
async def test_rules_are_filtered_by_namespace(store: SQLiteRelationalStore) -> None:
    telegram_rule = _make_rule("telegram ask", "reply telegram")
    telegram_rule.scope = MemoryScope(
        primary_namespace="channel:telegram",
        namespaces=["global", "channel:telegram"],
        channel_id="telegram",
    )
    feishu_rule = _make_rule("feishu ask", "reply feishu")
    feishu_rule.scope = MemoryScope(
        primary_namespace="channel:feishu",
        namespaces=["global", "channel:feishu"],
        channel_id="feishu",
    )

    await store.create_rule(telegram_rule)
    await store.create_rule(feishu_rule)

    telegram_results = await store.search_rules("ask", namespaces=["channel:telegram"])
    assert len(telegram_results) == 1
    assert telegram_results[0].scope.channel_id == "telegram"
    assert await store.count_rules(namespaces=["channel:feishu"]) == 1


# ── Tool-scoped rules ────────────────────────────────────────────────


def _make_tool_rule(
    tool_name: str, priority: str = "normal", trigger: str = "t", action: str = "a"
) -> ProceduralMemory:
    from myrm_agent_harness.toolkits.memory.types import ToolRulePriority

    return ProceduralMemory(
        content=f"When: {trigger} → Do: {action}",
        trigger=trigger,
        action=action,
        priority=1,
        tool_name=tool_name,
        tool_rule_priority=ToolRulePriority(priority),
    )


@pytest.mark.asyncio
async def test_create_rule_with_tool_fields(store: SQLiteRelationalStore) -> None:
    """tool_name and tool_rule_priority are persisted and retrievable."""
    from myrm_agent_harness.toolkits.memory.types import ToolRulePriority

    rule = _make_tool_rule("bash_code_execute_tool", "critical", "using sudo", "reject")
    created = await store.create_rule(rule)
    fetched = await store.get_rule(created.id)
    assert fetched is not None
    assert fetched.tool_name == "bash_code_execute_tool"
    assert fetched.tool_rule_priority == ToolRulePriority.CRITICAL


@pytest.mark.asyncio
async def test_create_rule_persists_expected_valid_days(
    store: SQLiteRelationalStore,
) -> None:
    """expected_valid_days round-trips through create/get/update."""
    rule = _make_tool_rule(
        "web_fetch_tool",
        trigger="repeated timeout",
        action="retry with fallback",
    )
    rule.expected_valid_days = 1
    rule.metadata["origin"] = "tool_failure"
    created = await store.create_rule(rule)
    fetched = await store.get_rule(created.id)
    assert fetched is not None
    assert fetched.expected_valid_days == 1
    assert fetched.metadata.get("origin") == "tool_failure"

    fetched.expected_valid_days = 3
    updated = await store.update_rule(fetched.id, fetched)
    re_fetched = await store.get_rule(updated.id)
    assert re_fetched is not None
    assert re_fetched.expected_valid_days == 3

    listed = await store.list_rules(active_only=True)
    assert any(r.id == created.id and r.expected_valid_days == 3 for r in listed)


@pytest.mark.asyncio
async def test_update_rule_preserves_tool_fields(store: SQLiteRelationalStore) -> None:
    """update_rule correctly persists tool_name and tool_rule_priority."""
    from myrm_agent_harness.toolkits.memory.types import ToolRulePriority

    created = await store.create_rule(_make_tool_rule("web_fetch_tool", "normal"))
    updated_rule = _make_tool_rule(
        "web_fetch_tool", "critical", "timeout retry", "use exponential backoff"
    )
    updated = await store.update_rule(created.id, updated_rule)
    assert updated.tool_rule_priority == ToolRulePriority.CRITICAL

    fetched = await store.get_rule(created.id)
    assert fetched is not None
    assert fetched.tool_rule_priority == ToolRulePriority.CRITICAL
    assert fetched.tool_name == "web_fetch_tool"


# ── Pending ──────────────────────────────────────────────────────────


def _make_pending(content: str = "test memory") -> PendingRecord:
    return PendingRecord(memory_type=MemoryType.SEMANTIC, content=content)


@pytest.mark.asyncio
async def test_submit_and_get_pending(store: SQLiteRelationalStore) -> None:
    record = _make_pending()
    pid = await store.submit_pending(record)
    fetched = await store.get_pending(pid)
    assert fetched is not None
    assert fetched.content == "test memory"
    assert fetched.status == "pending"


@pytest.mark.asyncio
async def test_pending_exists(store: SQLiteRelationalStore) -> None:
    await store.submit_pending(_make_pending("unique content"))
    assert await store.pending_exists("semantic", "unique content") is True
    assert await store.pending_exists("semantic", "other") is False


@pytest.mark.asyncio
async def test_mark_pending(store: SQLiteRelationalStore) -> None:
    record = _make_pending()
    pid = await store.submit_pending(record)
    await store.mark_pending(pid, "approved")
    fetched = await store.get_pending(pid)
    assert fetched is not None
    assert fetched.status == "approved"
    assert fetched.resolved_at is not None


@pytest.mark.asyncio
async def test_list_and_count_pending(store: SQLiteRelationalStore) -> None:
    for i in range(3):
        await store.submit_pending(_make_pending(f"mem_{i}"))
    pending = await store.list_pending()
    assert len(pending) == 3
    assert await store.count_pending() == 3


@pytest.mark.asyncio
async def test_batch_mark_pending(store: SQLiteRelationalStore) -> None:
    ids = []
    for i in range(3):
        pid = await store.submit_pending(_make_pending(f"batch_{i}"))
        ids.append(pid)
    count = await store.batch_mark_pending(ids[:2], "rejected")
    assert count == 2
    assert await store.count_pending() == 1


# ── Delete all ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_all(store: SQLiteRelationalStore) -> None:
    await store.set_profile("k", "v")
    await store.create_rule(_make_rule())
    await store.submit_pending(_make_pending())
    count = await store.delete_all()
    assert count >= 3
    assert await store.count_profiles() == 0
    assert await store.count_rules() == 0
    assert await store.count_pending() == 0


# ── Lifecycle ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_context_manager(tmp_path: Path) -> None:
    async with SQLiteRelationalStore(str(tmp_path / "ctx.db")) as s:
        await s.set_profile("test", "value")
        assert await s.get_profile("test") == "value"


# ── Profile snapshot ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_profile_snapshot_exists(store: SQLiteRelationalStore) -> None:
    await store.set_profile("language", "zh")
    snap = await store.get_profile_snapshot("language")
    assert snap.exists is True
    assert snap.key == "language"
    assert snap.value == "zh"
    assert snap.revision is not None
    assert snap.updated_at is not None


@pytest.mark.asyncio
async def test_get_profile_snapshot_not_found(store: SQLiteRelationalStore) -> None:
    snap = await store.get_profile_snapshot("nonexistent")
    assert snap.exists is False
    assert snap.key == "nonexistent"
    assert "missing" in snap.revision


@pytest.mark.asyncio
async def test_list_rules_active_only_false(store: SQLiteRelationalStore) -> None:
    rule = _make_rule("trigger", "action")
    rule.is_active = False
    await store.create_rule(rule)
    await store.create_rule(_make_rule("active trigger", "active action"))

    all_rules = await store.list_rules(active_only=False)
    assert len(all_rules) == 2

    active_rules = await store.list_rules(active_only=True)
    assert len(active_rules) == 1


# ── Pending by source chat ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_pending_by_source_chat_id(store: SQLiteRelationalStore) -> None:
    """delete_pending_by_source_chat_id removes only matching records."""
    record = _make_pending("chat-scoped")
    record.source_chat_id = "chat-1"
    await store.submit_pending(record)
    await store.submit_pending(_make_pending("other"))

    deleted = await store.delete_pending_by_source_chat_id("chat-1")
    assert deleted == 1
    assert await store.count_pending() == 1


@pytest.mark.asyncio
async def test_count_pending_by_source_chat_id(store: SQLiteRelationalStore) -> None:
    """count_pending_by_source_chat_id counts only matching records."""
    for i in range(3):
        record = _make_pending(f"chat-{i}")
        record.source_chat_id = "chat-1"
        await store.submit_pending(record)
    await store.submit_pending(_make_pending("other"))

    assert await store.count_pending_by_source_chat_id("chat-1") == 3
    assert await store.count_pending_by_source_chat_id("missing") == 0


@pytest.mark.asyncio
async def test_batch_mark_pending_empty_list(store: SQLiteRelationalStore) -> None:
    """batch_mark_pending with empty list returns 0 without touching DB."""
    assert await store.batch_mark_pending([], "rejected") == 0


# ── Lifecycle edge cases ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_operations_after_close_raise(store: SQLiteRelationalStore) -> None:
    """Any operation after close() must raise RelationalConnectionError."""
    from myrm_agent_harness.toolkits.memory.relational.exceptions import (
        RelationalConnectionError,
    )

    await store.close()
    with pytest.raises(RelationalConnectionError):
        await store.get_profile("language")


@pytest.mark.asyncio
async def test_close_is_idempotent(store: SQLiteRelationalStore) -> None:
    """close() can be called multiple times safely."""
    await store.set_profile("k", "v")
    await store.close()
    await store.close()
    assert store._closed is True


# ── Error branches ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_query_error_branches_raise(
    store: SQLiteRelationalStore, monkeypatch
) -> None:
    """DB failures surface as RelationalQueryError across CRUD methods."""
    from myrm_agent_harness.toolkits.memory.relational.exceptions import (
        RelationalQueryError,
    )

    class _ExplodingCursor:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return False

        async def execute(self, *_args, **_kwargs):
            raise RuntimeError("db exploded")

        async def commit(self):
            raise RuntimeError("db exploded")

        async def fetchone(self):
            raise RuntimeError("db exploded")

        async def fetchall(self):
            raise RuntimeError("db exploded")

    class _ExplodingConnection:
        def execute(self, *_args, **_kwargs):
            return _ExplodingCursor()

        async def commit(self):
            raise RuntimeError("db exploded")

    async def _fake_connection():
        return _ExplodingConnection()

    monkeypatch.setattr(store, "_get_connection", _fake_connection)

    for call in (
        lambda: store.get_profile("k"),
        lambda: store.get_profile_snapshot("k"),
        lambda: store.set_profile("k", "v"),
        lambda: store.delete_profile("k"),
        lambda: store.list_profiles(),
        lambda: store.count_profiles(),
        lambda: store.create_rule(_make_rule()),
        lambda: store.get_rule("r"),
        lambda: store.search_rules("q"),
        lambda: store.list_rules(),
        lambda: store.count_rules(),
        lambda: store.update_rule("r", _make_rule()),
        lambda: store.delete_rule("r"),
        lambda: store.delete_all(),
        lambda: store.submit_pending(_make_pending()),
        lambda: store.get_pending("p"),
        lambda: store.pending_exists("semantic", "c"),
        lambda: store.mark_pending("p", "approved"),
        lambda: store.list_pending(),
        lambda: store.count_pending(),
        lambda: store.batch_mark_pending(["p"], "approved"),
        lambda: store.delete_pending_by_source_chat_id("chat"),
        lambda: store.count_pending_by_source_chat_id("chat"),
    ):
        with pytest.raises(RelationalQueryError):
            await call()
