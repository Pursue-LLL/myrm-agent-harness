"""Unit tests for StalenessGuard — content hash based file staleness detection."""

from __future__ import annotations

from unittest.mock import MagicMock

from myrm_agent_harness.agent.meta_tools.file_ops.core.staleness_guard import (
    StalenessGuard,
    _staleness_guards,
    get_staleness_guard,
)


class TestStalenessGuard:
    """Core StalenessGuard class tests."""

    def test_no_warning_on_unchanged_file(self) -> None:
        guard = StalenessGuard()
        guard.record_read("/a/b.py", "hello")
        assert guard.check_staleness("/a/b.py", "hello") is None

    def test_warning_on_modified_file(self) -> None:
        guard = StalenessGuard()
        guard.record_read("/a/b.py", "hello")
        warning = guard.check_staleness("/a/b.py", "modified")
        assert warning is not None
        assert "modified since your last read" in warning

    def test_no_warning_for_unread_file(self) -> None:
        guard = StalenessGuard()
        assert guard.check_staleness("/unknown.py", "anything") is None

    def test_record_write_prevents_false_positive(self) -> None:
        """After write, consecutive edit should not warn."""
        guard = StalenessGuard()
        guard.record_read("/a/b.py", "v1")
        guard.record_write("/a/b.py", "v2")
        assert guard.check_staleness("/a/b.py", "v2") is None

    def test_record_write_then_external_change_warns(self) -> None:
        """After write, if external change occurs, should warn."""
        guard = StalenessGuard()
        guard.record_read("/a/b.py", "v1")
        guard.record_write("/a/b.py", "v2")
        warning = guard.check_staleness("/a/b.py", "external_v3")
        assert warning is not None

    def test_path_normalization(self) -> None:
        """Paths should be normalized (e.g. ./foo and foo are the same)."""
        guard = StalenessGuard()
        guard.record_read("./a/b.py", "hello")
        assert guard.check_staleness("a/b.py", "hello") is None
        assert guard.check_staleness("a/b.py", "changed") is not None

    def test_path_normalization_double_slash(self) -> None:
        guard = StalenessGuard()
        guard.record_read("/a//b.py", "hello")
        assert guard.check_staleness("/a/b.py", "hello") is None

    def test_clear(self) -> None:
        guard = StalenessGuard()
        guard.record_read("/a.py", "x")
        guard.clear()
        assert guard.check_staleness("/a.py", "y") is None

    def test_multiple_files(self) -> None:
        guard = StalenessGuard()
        guard.record_read("/a.py", "aa")
        guard.record_read("/b.py", "bb")
        assert guard.check_staleness("/a.py", "aa") is None
        assert guard.check_staleness("/b.py", "bb") is None
        assert guard.check_staleness("/a.py", "changed") is not None
        assert guard.check_staleness("/b.py", "bb") is None


class TestStalenessGuardAgentAware:
    """Agent-aware isolation tests for concurrent subagent scenarios."""

    def test_different_agents_independent_reads(self) -> None:
        """Agent A and Agent B read the same file — each tracks independently."""
        guard = StalenessGuard()
        guard.record_read("/f.py", "v1", agent_id="agent-a")
        guard.record_read("/f.py", "v1", agent_id="agent-b")

        # Agent A's file gets modified externally
        assert guard.check_staleness("/f.py", "modified", agent_id="agent-a") is not None
        # Agent B also sees the modification
        assert guard.check_staleness("/f.py", "modified", agent_id="agent-b") is not None

    def test_agent_write_does_not_mask_other_agent(self) -> None:
        """Agent A's write must NOT mask Agent B's staleness detection (the core bug fix)."""
        guard = StalenessGuard()
        guard.record_read("/f.py", "v1", agent_id="agent-a")
        guard.record_read("/f.py", "v1", agent_id="agent-b")

        # Agent A writes to the file
        guard.record_write("/f.py", "v2", agent_id="agent-a")

        # Agent A sees the updated hash — no warning
        assert guard.check_staleness("/f.py", "v2", agent_id="agent-a") is None

        # Agent B still has v1 hash — the file changed, so it should warn
        assert guard.check_staleness("/f.py", "v2", agent_id="agent-b") is not None

    def test_clear_agent_removes_one_agent_only(self) -> None:
        guard = StalenessGuard()
        guard.record_read("/f.py", "v1", agent_id="agent-a")
        guard.record_read("/f.py", "v1", agent_id="agent-b")

        guard.clear_agent("agent-a")

        # Agent A's records are gone — no warning (never read)
        assert guard.check_staleness("/f.py", "changed", agent_id="agent-a") is None
        # Agent B still tracks — should warn
        assert guard.check_staleness("/f.py", "changed", agent_id="agent-b") is not None

    def test_clear_removes_all_agents(self) -> None:
        guard = StalenessGuard()
        guard.record_read("/f.py", "v1", agent_id="agent-a")
        guard.record_read("/f.py", "v1", agent_id="agent-b")

        guard.clear()

        assert guard.check_staleness("/f.py", "changed", agent_id="agent-a") is None
        assert guard.check_staleness("/f.py", "changed", agent_id="agent-b") is None

    def test_default_agent_id_when_no_context(self) -> None:
        """When no explicit agent_id, uses default (__main__)."""
        guard = StalenessGuard()
        guard.record_read("/f.py", "v1")
        # Without subagent context, should use __main__
        assert guard.check_staleness("/f.py", "v1") is None
        assert guard.check_staleness("/f.py", "changed") is not None

    def test_clear_agent_nonexistent_is_safe(self) -> None:
        """Clearing a non-existent agent should not raise."""
        guard = StalenessGuard()
        guard.clear_agent("does-not-exist")

    def test_reread_updates_hash(self) -> None:
        """Re-reading a file should update the stored hash."""
        guard = StalenessGuard()
        guard.record_read("/f.py", "v1", agent_id="a")
        guard.record_read("/f.py", "v2", agent_id="a")
        assert guard.check_staleness("/f.py", "v2", agent_id="a") is None
        assert guard.check_staleness("/f.py", "v1", agent_id="a") is not None

    def test_unread_agent_returns_none(self) -> None:
        """An agent that never read a file should get None (not a stale warning)."""
        guard = StalenessGuard()
        guard.record_read("/f.py", "v1", agent_id="a")
        assert guard.check_staleness("/f.py", "anything", agent_id="b") is None


class TestGetStalenessGuard:
    """Module-level factory function tests."""

    def test_returns_none_for_no_executor(self) -> None:
        assert get_staleness_guard(None) is None

    def test_returns_guard_for_executor(self) -> None:
        executor = MagicMock()
        guard = get_staleness_guard(executor)
        assert guard is not None
        assert isinstance(guard, StalenessGuard)

    def test_same_executor_same_guard(self) -> None:
        executor = MagicMock()
        g1 = get_staleness_guard(executor)
        g2 = get_staleness_guard(executor)
        assert g1 is g2

    def test_different_executors_different_guards(self) -> None:
        e1 = MagicMock()
        e2 = MagicMock()
        g1 = get_staleness_guard(e1)
        g2 = get_staleness_guard(e2)
        assert g1 is not g2

    def teardown_method(self) -> None:
        _staleness_guards.clear()


class TestReadBeforeEditGate:
    """Tests for the read-before-edit gate (require_read_before_write)."""

    def test_gate_blocks_unread_file(self) -> None:
        guard = StalenessGuard()
        rejection = guard.require_read_before_write("/unread.py")
        assert rejection is not None
        assert "has not been read" in rejection

    def test_gate_passes_after_full_read(self) -> None:
        guard = StalenessGuard()
        guard.record_read("/a.py", "content")
        assert guard.require_read_before_write("/a.py") is None

    def test_gate_passes_after_partial_read(self) -> None:
        guard = StalenessGuard()
        guard.record_read_marker("/a.py")
        assert guard.require_read_before_write("/a.py") is None

    def test_gate_passes_after_write(self) -> None:
        guard = StalenessGuard()
        guard.record_write("/a.py", "content")
        assert guard.require_read_before_write("/a.py") is None

    def test_gate_blocks_after_clear(self) -> None:
        guard = StalenessGuard()
        guard.record_read("/a.py", "content")
        guard.clear()
        rejection = guard.require_read_before_write("/a.py")
        assert rejection is not None

    def test_gate_agent_isolation(self) -> None:
        guard = StalenessGuard()
        guard.record_read("/a.py", "content", agent_id="agent-a")
        # agent-a read it, gate passes
        assert guard.require_read_before_write("/a.py", agent_id="agent-a") is None
        # agent-b never read it, gate blocks
        rejection = guard.require_read_before_write("/a.py", agent_id="agent-b")
        assert rejection is not None

    def test_gate_path_normalization(self) -> None:
        guard = StalenessGuard()
        guard.record_read("./dir/../a.py", "content")
        assert guard.require_read_before_write("a.py") is None


class TestRecordReadMarker:
    """Tests for partial read marker (record_read_marker)."""

    def test_marker_does_not_overwrite_full_hash(self) -> None:
        guard = StalenessGuard()
        guard.record_read("/a.py", "full_content")
        guard.record_read_marker("/a.py")
        # Staleness should still work (hash preserved, not replaced by sentinel)
        warning = guard.check_staleness("/a.py", "changed")
        assert warning is not None

    def test_marker_skips_staleness_check(self) -> None:
        guard = StalenessGuard()
        guard.record_read_marker("/a.py")
        # Staleness returns None for sentinel (cannot detect changes from partial read)
        assert guard.check_staleness("/a.py", "anything") is None

    def test_full_read_upgrades_marker(self) -> None:
        guard = StalenessGuard()
        guard.record_read_marker("/a.py")
        guard.record_read("/a.py", "full_content")
        # Now staleness detection works
        assert guard.check_staleness("/a.py", "full_content") is None
        assert guard.check_staleness("/a.py", "different") is not None

    def test_marker_agent_isolation(self) -> None:
        guard = StalenessGuard()
        guard.record_read_marker("/a.py", agent_id="agent-a")
        # agent-a has marker
        assert guard.require_read_before_write("/a.py", agent_id="agent-a") is None
        # agent-b does not
        rejection = guard.require_read_before_write("/a.py", agent_id="agent-b")
        assert rejection is not None


class TestEdgeCases:
    """Edge case scenarios for completeness."""

    def test_empty_file_content_does_not_conflict_with_sentinel(self) -> None:
        """Empty file hash (md5('')) != sentinel (''), so staleness still works."""
        guard = StalenessGuard()
        guard.record_read("/empty.py", "")
        # Hash of "" is "d41d8cd98f00b204e9800998ecf8427e", not ""
        # So staleness should detect if content changes to non-empty
        warning = guard.check_staleness("/empty.py", "now has content")
        assert warning is not None
        # And no false positive when content is still empty
        assert guard.check_staleness("/empty.py", "") is None

    def test_gate_passes_after_create_then_edit(self) -> None:
        """After record_write (CREATE), STR_REPLACE gate should pass."""
        guard = StalenessGuard()
        # Simulates CREATE operation calling record_write
        guard.record_write("/new.py", "initial content")
        # Subsequent edit should pass the gate
        assert guard.require_read_before_write("/new.py") is None

    def test_clear_agent_then_other_agent_unaffected(self) -> None:
        """Clearing one agent doesn't affect another's gate status."""
        guard = StalenessGuard()
        guard.record_read("/f.py", "v1", agent_id="a")
        guard.record_read("/f.py", "v1", agent_id="b")
        guard.clear_agent("a")
        # agent-a gate blocked
        assert guard.require_read_before_write("/f.py", agent_id="a") is not None
        # agent-b gate still passes
        assert guard.require_read_before_write("/f.py", agent_id="b") is None

    def test_staleness_after_partial_read_then_full_read(self) -> None:
        """Partial read then full read: staleness should work after full read."""
        guard = StalenessGuard()
        guard.record_read_marker("/f.py")
        guard.record_read("/f.py", "full content v1")
        # Now staleness detection should work
        assert guard.check_staleness("/f.py", "full content v1") is None
        assert guard.check_staleness("/f.py", "modified") is not None

    def test_multiple_writes_update_hash(self) -> None:
        """Multiple writes should keep hash up to date."""
        guard = StalenessGuard()
        guard.record_read("/f.py", "v1")
        guard.record_write("/f.py", "v2")
        guard.record_write("/f.py", "v3")
        assert guard.check_staleness("/f.py", "v3") is None
        assert guard.check_staleness("/f.py", "v2") is not None
