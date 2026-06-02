"""Extended tests for approval_flow module to achieve 80%+ coverage.

Covers: TTL-based load_user, _cleanup_expired_locks, remove with store,
clear_user, set_allowlist_store, _get_or_create_lock, DEFAULT_USER_ID.
"""

import asyncio
import time

import pytest

from myrm_agent_harness.agent.security.approval_flow import (
    DEFAULT_USER_ID,
    Allowlist,
    AllowlistEntry,
    get_allowlist,
    set_allowlist_store,
)


class FakeStore:
    """Fake AllowlistStore matching the AllowlistStore Protocol."""

    def __init__(self) -> None:
        self.saved: list[tuple[str, AllowlistEntry]] = []
        self.removed: list[tuple[str, str, str | None, str | None]] = []
        self.load_calls: list[str] = []
        self._data: dict[str, list[AllowlistEntry]] = {}

    async def load(self, user_id: str) -> list[AllowlistEntry]:
        self.load_calls.append(user_id)
        return self._data.get(user_id, [])

    async def save(self, user_id: str, entry: AllowlistEntry) -> None:
        self.saved.append((user_id, entry))
        self._data.setdefault(user_id, []).append(entry)

    async def remove(
        self, user_id: str, permission: str, tool_name: str | None = None, tool_args_hash: str | None = None
    ) -> None:
        self.removed.append((user_id, permission, tool_name, tool_args_hash))


class TestDefaultUserID:
    def test_default_user_id_is_sandbox(self):
        assert DEFAULT_USER_ID == "sandbox"


class TestAllowlistWithStore:
    @pytest.fixture
    def store(self) -> FakeStore:
        return FakeStore()

    @pytest.fixture
    def allowlist(self, store: FakeStore) -> Allowlist:
        return Allowlist(store=store, ttl_seconds=300.0)

    @pytest.mark.asyncio
    async def test_load_user_from_store(self, allowlist: Allowlist, store: FakeStore):
        store._data["user1"] = [
            AllowlistEntry(permission="shell_exec", tool_name="bash_code_execute_tool"),
        ]

        await allowlist.load_user("user1")

        assert store.load_calls == ["user1"]
        assert allowlist.check("user1", "shell_exec", "bash_code_execute_tool")

    @pytest.mark.asyncio
    async def test_load_user_cache_hit_skips_store(self, allowlist: Allowlist, store: FakeStore):
        store._data["user1"] = [AllowlistEntry(permission="shell_exec")]

        await allowlist.load_user("user1")
        await allowlist.load_user("user1")

        assert len(store.load_calls) == 1, "Second call should hit cache"

    @pytest.mark.asyncio
    async def test_load_user_ttl_expired_reloads(self, store: FakeStore):
        allowlist = Allowlist(store=store, ttl_seconds=0.01)
        store._data["user1"] = [AllowlistEntry(permission="shell_exec")]

        await allowlist.load_user("user1")
        assert len(store.load_calls) == 1

        await asyncio.sleep(0.02)

        store._data["user1"] = [
            AllowlistEntry(permission="shell_exec"),
            AllowlistEntry(permission="file_write"),
        ]
        await allowlist.load_user("user1")

        assert len(store.load_calls) == 2, "Should reload after TTL expires"
        assert allowlist.check("user1", "file_write")

    @pytest.mark.asyncio
    async def test_load_user_no_store_returns_early(self):
        allowlist = Allowlist(store=None)
        await allowlist.load_user("user1")
        assert not allowlist.check("user1", "shell_exec")

    @pytest.mark.asyncio
    async def test_add_persists_to_store(self, allowlist: Allowlist, store: FakeStore):
        entry = AllowlistEntry(permission="network")
        await allowlist.add("user1", entry)

        assert len(store.saved) == 1
        assert store.saved[0] == ("user1", entry)

    @pytest.mark.asyncio
    async def test_add_deduplicates(self, allowlist: Allowlist, store: FakeStore):
        entry = AllowlistEntry(permission="network")
        await allowlist.add("user1", entry)
        await allowlist.add("user1", entry)

        assert len(store.saved) == 1, "Duplicate should be skipped"

    @pytest.mark.asyncio
    async def test_remove_persists_to_store(self, allowlist: Allowlist, store: FakeStore):
        entry = AllowlistEntry(permission="shell_exec")
        await allowlist.add("user1", entry)
        assert allowlist.check("user1", "shell_exec")

        await allowlist.remove("user1", "shell_exec")
        assert not allowlist.check("user1", "shell_exec")
        assert len(store.removed) == 1

    @pytest.mark.asyncio
    async def test_clear_user(self, allowlist: Allowlist, store: FakeStore):
        await allowlist.add("user1", AllowlistEntry(permission="shell_exec"))
        await allowlist.add("user1", AllowlistEntry(permission="file_write"))
        await allowlist.add("user1", AllowlistEntry(permission="network"))

        count = await allowlist.clear_user("user1")
        assert count == 3
        assert not allowlist.check("user1", "shell_exec")
        assert not allowlist.check("user1", "file_write")
        assert not allowlist.check("user1", "network")

    @pytest.mark.asyncio
    async def test_clear_user_empty(self, allowlist: Allowlist):
        count = await allowlist.clear_user("nonexistent")
        assert count == 0


class TestAllowlistTTLCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_expired_locks(self):
        allowlist = Allowlist(store=None, ttl_seconds=0.01)

        await allowlist.add("user1", AllowlistEntry(permission="shell_exec"))
        await allowlist.add("user2", AllowlistEntry(permission="file_write"))

        await asyncio.sleep(0.03)

        await allowlist.add("user3", AllowlistEntry(permission="network"))

        assert allowlist.check("user3", "network")

    @pytest.mark.asyncio
    async def test_cleanup_actually_removes_expired(self):
        """Verify expired locks are actually removed from _cache_meta and _entries.

        _cleanup_expired_locks is only called inside load_user when is_new=True.
        We must use load_user (not add) to trigger the real cleanup path.
        """
        store = FakeStore()
        allowlist = Allowlist(store=store, ttl_seconds=0.005)

        store._data["expired_user"] = [AllowlistEntry(permission="shell_exec")]
        await allowlist.load_user("expired_user")
        assert "expired_user" in allowlist._cache_meta

        await asyncio.sleep(0.03)

        store._data["fresh_user"] = [AllowlistEntry(permission="network")]
        await allowlist.load_user("fresh_user")

        assert "expired_user" not in allowlist._cache_meta, \
            "expired_user should be cleaned from cache_meta"
        assert allowlist.check("fresh_user", "network")

    @pytest.mark.asyncio
    async def test_no_cleanup_when_ttl_disabled(self):
        allowlist = Allowlist(store=None, ttl_seconds=0)

        await allowlist.add("user1", AllowlistEntry(permission="shell_exec"))
        assert allowlist.check("user1", "shell_exec")

        await allowlist.add("user2", AllowlistEntry(permission="file_write"))
        assert allowlist.check("user1", "shell_exec"), "Should still be valid"

    @pytest.mark.asyncio
    async def test_cleanup_ttl_zero_no_cleanup(self):
        """Explicitly verify _cleanup_expired_locks is no-op when ttl <= 0."""
        allowlist = Allowlist(store=None, ttl_seconds=0)
        allowlist._cleanup_expired_locks()
        # No crash, no removal

    @pytest.mark.asyncio
    async def test_is_cache_fresh_no_ttl(self):
        allowlist = Allowlist(store=None, ttl_seconds=-1)
        assert allowlist._is_cache_fresh(time.time() - 99999) is True

    @pytest.mark.asyncio
    async def test_is_cache_fresh_none_timestamp(self):
        allowlist = Allowlist(store=None, ttl_seconds=300)
        assert allowlist._is_cache_fresh(None) is False

    @pytest.mark.asyncio
    async def test_load_user_double_check_inside_lock(self):
        """Test the double-check TTL path inside the per-user lock (line 163-164).

        Simulate: two concurrent load_user calls when TTL expired.
        Task A acquires lock and reloads; Task B waits for lock then hits
        the double-check fresh-cache early return.
        """
        store = FakeStore()
        allowlist = Allowlist(store=store, ttl_seconds=0.01)
        store._data["user1"] = [AllowlistEntry(permission="shell_exec")]

        await allowlist.load_user("user1")
        assert len(store.load_calls) == 1

        await asyncio.sleep(0.02)

        barrier = asyncio.Event()
        original_load = store.load

        async def slow_load(user_id: str) -> list[AllowlistEntry]:
            """First call: signal then delay so Task B queues behind the lock."""
            barrier.set()
            await asyncio.sleep(0.05)
            return await original_load(user_id)

        store.load = slow_load  # type: ignore[assignment]

        async def task_a() -> None:
            await allowlist.load_user("user1")

        async def task_b() -> None:
            await barrier.wait()
            await asyncio.sleep(0.005)
            store.load = original_load  # type: ignore[assignment]
            await allowlist.load_user("user1")

        await asyncio.gather(task_a(), task_b())
        assert len(store.load_calls) == 2, "Only Task A should call store.load; Task B hits double-check"


class TestSetAllowlistStore:
    def test_set_allowlist_store_replaces_global(self):
        import myrm_agent_harness.agent.security.approval_flow as mod

        old = mod._allowlist
        store = FakeStore()
        set_allowlist_store(store)

        new_allowlist = get_allowlist()
        assert new_allowlist is not old
        assert new_allowlist._store is store

        mod._allowlist = None

    def test_get_allowlist_creates_singleton(self):
        """get_allowlist creates Allowlist when _allowlist is None (line 276-277)."""
        import myrm_agent_harness.agent.security.approval_flow as mod

        original = mod._allowlist
        mod._allowlist = None
        try:
            result = get_allowlist()
            assert isinstance(result, Allowlist)
            assert result._store is None
            assert get_allowlist() is result, "Singleton should return same instance"
        finally:
            mod._allowlist = original


class TestGetOrCreateLock:
    @pytest.mark.asyncio
    async def test_existing_user_returns_same_lock(self):
        allowlist = Allowlist(store=None)
        await allowlist.add("user1", AllowlistEntry(permission="shell_exec"))

        _ts1, lock1, is_new1 = allowlist._get_or_create_lock("user1")
        assert not is_new1

        _ts2, lock2, _is_new2 = allowlist._get_or_create_lock("user1")
        assert lock1 is lock2

    @pytest.mark.asyncio
    async def test_new_user_creates_lock(self):
        allowlist = Allowlist(store=None)
        ts, lock, is_new = allowlist._get_or_create_lock("new_user")
        assert is_new
        assert ts is None
        assert isinstance(lock, asyncio.Lock)
