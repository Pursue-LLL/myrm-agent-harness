"""Unit tests for ReadDedupGuard (read-time dedup to protect Prompt Cache)."""

from myrm_agent_harness.agent.meta_tools.file_ops.core.read_dedup import (
    _DEDUP_BLOCK_THRESHOLD,
    DedupResult,
    ReadDedupGuard,
    _dedup_enabled,
    get_read_dedup_guard,
    reset_all_read_dedup,
)


class _FakeExecutor:
    """Minimal executor stub for get_read_dedup_guard isolation checks."""


def test_dedup_enabled_default_on():
    """Kill-switch defaults to enabled."""
    assert _dedup_enabled() is True


def test_dedup_enabled_kill_switch(monkeypatch):
    """Kill-switch disables dedup."""
    monkeypatch.setenv("MYRM_READ_DEDUP_ENABLED", "0")
    assert _dedup_enabled() is False


def test_first_read_is_miss():
    """First read of a key is always a miss (records state)."""
    guard = ReadDedupGuard()
    result = guard.check("/tmp/a.txt", None, mtime=100.0, agent_id="a")
    assert result.kind == DedupResult.MISS
    assert result.is_hit is False


def test_unchanged_second_read_is_stub():
    """Same mtime second read returns a stub (content unchanged)."""
    guard = ReadDedupGuard()
    guard.check("/tmp/a.txt", None, mtime=100.0, agent_id="a")
    result = guard.check("/tmp/a.txt", None, mtime=100.0, agent_id="a")
    assert result.kind == DedupResult.STUB
    assert result.is_hit is True
    assert result.hits == 1


def test_changed_mtime_is_miss():
    """A different mtime resets dedup and returns a miss."""
    guard = ReadDedupGuard()
    guard.check("/tmp/a.txt", None, mtime=100.0, agent_id="a")
    result = guard.check("/tmp/a.txt", None, mtime=200.0, agent_id="a")
    assert result.kind == DedupResult.MISS


def test_hard_block_after_threshold():
    """Repeated unchanged reads escalate to a hard block."""
    guard = ReadDedupGuard()
    guard.check("/tmp/a.txt", None, mtime=100.0, agent_id="a")
    guard.check("/tmp/a.txt", None, mtime=100.0, agent_id="a")  # stub
    result = guard.check("/tmp/a.txt", None, mtime=100.0, agent_id="a")
    assert result.kind == DedupResult.BLOCKED
    assert result.hits == _DEDUP_BLOCK_THRESHOLD


def test_view_range_is_part_of_key():
    """Different view ranges are distinct dedup keys."""
    guard = ReadDedupGuard()
    guard.check("/tmp/a.txt", "1:10", mtime=100.0, agent_id="a")
    result = guard.check("/tmp/a.txt", "11:20", mtime=100.0, agent_id="a")
    assert result.kind == DedupResult.MISS


def test_invalidate_drops_state():
    """invalidate clears dedup so the next read is a miss (write invalidation)."""
    guard = ReadDedupGuard()
    guard.check("/tmp/a.txt", None, mtime=100.0, agent_id="a")
    guard.invalidate("/tmp/a.txt", agent_id="a")
    result = guard.check("/tmp/a.txt", None, mtime=100.0, agent_id="a")
    assert result.kind == DedupResult.MISS


def test_agent_isolation():
    """Dedup state is isolated per agent."""
    guard = ReadDedupGuard()
    guard.check("/tmp/a.txt", None, mtime=100.0, agent_id="a")
    result = guard.check("/tmp/a.txt", None, mtime=100.0, agent_id="b")
    assert result.kind == DedupResult.MISS


def test_clear_agent():
    """clear_agent clears only that agent's state."""
    guard = ReadDedupGuard()
    guard.check("/tmp/a.txt", None, mtime=100.0, agent_id="a")
    guard.check("/tmp/a.txt", None, mtime=100.0, agent_id="b")
    guard.clear_agent("a")
    assert (
        guard.check("/tmp/a.txt", None, mtime=100.0, agent_id="a").kind
        == DedupResult.MISS
    )
    assert (
        guard.check("/tmp/a.txt", None, mtime=100.0, agent_id="b").kind
        == DedupResult.STUB
    )


def test_clear_all():
    """clear clears all agents' state."""
    guard = ReadDedupGuard()
    guard.check("/tmp/a.txt", None, mtime=100.0, agent_id="a")
    guard.clear()
    assert (
        guard.check("/tmp/a.txt", None, mtime=100.0, agent_id="a").kind
        == DedupResult.MISS
    )


def test_get_guard_none_for_no_executor():
    """No executor yields no guard (dedup skipped)."""
    assert get_read_dedup_guard(None) is None


def test_get_guard_isolation_per_executor():
    """Different executors get different guards."""
    e1 = _FakeExecutor()
    e2 = _FakeExecutor()
    g1 = get_read_dedup_guard(e1)
    g2 = get_read_dedup_guard(e2)
    assert g1 is not None
    assert g2 is not None
    assert g1 is not g2


def test_get_guard_same_executor_cached():
    """Same executor returns the same cached guard."""
    e = _FakeExecutor()
    assert get_read_dedup_guard(e) is get_read_dedup_guard(e)


def test_reset_all_read_dedup_clears_registry():
    """reset_all_read_dedup clears every executor's guard state."""
    e = _FakeExecutor()
    guard = get_read_dedup_guard(e)
    assert guard is not None
    guard.check("/tmp/a.txt", None, mtime=100.0, agent_id="a")
    reset_all_read_dedup()
    assert (
        guard.check("/tmp/a.txt", None, mtime=100.0, agent_id="a").kind
        == DedupResult.MISS
    )


def test_kill_switch_returns_miss(monkeypatch):
    """When disabled, check always returns a miss without recording state."""
    monkeypatch.setenv("MYRM_READ_DEDUP_ENABLED", "0")
    guard = ReadDedupGuard()
    guard.check("/tmp/a.txt", None, mtime=100.0, agent_id="a")
    result = guard.check("/tmp/a.txt", None, mtime=100.0, agent_id="a")
    assert result.kind == DedupResult.MISS


def test_current_agent_id_fallback_on_import_error(monkeypatch):
    """_current_agent_id falls back to the default agent when the session context is unavailable."""
    import builtins

    real_import = builtins.__import__

    def _broken_import(name, *args, **kwargs):
        if name == "myrm_agent_harness.agent.middlewares._session_context":
            raise ImportError("simulated missing module")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _broken_import)
    from myrm_agent_harness.agent.meta_tools.file_ops.core.read_dedup import (
        _current_agent_id,
    )

    assert _current_agent_id() == "__main__"


def test_invalidate_no_bucket_is_noop():
    """invalidate on an agent with no recorded state is a safe no-op."""
    guard = ReadDedupGuard()
    guard.invalidate("/tmp/a.txt", agent_id="ghost")
    # No exception raised; state remains empty.
    assert (
        guard.check("/tmp/a.txt", None, mtime=100.0, agent_id="ghost").kind
        == DedupResult.MISS
    )


def test_current_agent_id_default_when_subagent_none(monkeypatch):
    """_current_agent_id uses the default agent when get_subagent_task_id returns None."""
    import myrm_agent_harness.agent.middlewares._session_context as sc

    monkeypatch.setattr(sc, "get_subagent_task_id", lambda: None)
    from myrm_agent_harness.agent.meta_tools.file_ops.core.read_dedup import (
        _current_agent_id,
    )

    assert _current_agent_id() == "__main__"
