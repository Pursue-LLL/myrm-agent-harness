"""Unit tests for FileIntegrityGuard — read gate + version gate."""

from __future__ import annotations

from unittest.mock import MagicMock

from myrm_agent_harness.agent.meta_tools.file_ops.core.file_integrity_guard import (
    FileIntegrityGuard,
    _integrity_guards,
    get_file_integrity_guard,
)


class TestFileIntegrityGuard:
    """Core FileIntegrityGuard class tests."""

    def test_no_rejection_on_unchanged_file(self) -> None:
        guard = FileIntegrityGuard()
        guard.record_read("/a/b.py", "hello")
        assert guard.require_version_match("/a/b.py", "hello") is None

    def test_rejection_on_modified_file(self) -> None:
        guard = FileIntegrityGuard()
        guard.record_read("/a/b.py", "hello")
        rejection = guard.require_version_match("/a/b.py", "modified")
        assert rejection is not None
        assert "has changed on disk since your last read" in rejection

    def test_no_rejection_for_unread_file(self) -> None:
        guard = FileIntegrityGuard()
        assert guard.require_version_match("/unknown.py", "anything") is None

    def test_record_write_prevents_false_positive(self) -> None:
        guard = FileIntegrityGuard()
        guard.record_read("/a/b.py", "v1")
        guard.record_write("/a/b.py", "v2")
        assert guard.require_version_match("/a/b.py", "v2") is None

    def test_record_write_then_external_change_rejects(self) -> None:
        guard = FileIntegrityGuard()
        guard.record_read("/a/b.py", "v1")
        guard.record_write("/a/b.py", "v2")
        rejection = guard.require_version_match("/a/b.py", "external_v3")
        assert rejection is not None

    def test_path_normalization(self) -> None:
        guard = FileIntegrityGuard()
        guard.record_read("./a/b.py", "hello")
        assert guard.require_version_match("a/b.py", "hello") is None
        assert guard.require_version_match("a/b.py", "changed") is not None

    def test_path_normalization_double_slash(self) -> None:
        guard = FileIntegrityGuard()
        guard.record_read("/a//b.py", "hello")
        assert guard.require_version_match("/a/b.py", "hello") is None

    def test_clear(self) -> None:
        guard = FileIntegrityGuard()
        guard.record_read("/a.py", "x")
        guard.clear()
        assert guard.require_version_match("/a.py", "y") is None

    def test_multiple_files(self) -> None:
        guard = FileIntegrityGuard()
        guard.record_read("/a.py", "aa")
        guard.record_read("/b.py", "bb")
        assert guard.require_version_match("/a.py", "aa") is None
        assert guard.require_version_match("/b.py", "bb") is None
        assert guard.require_version_match("/a.py", "changed") is not None
        assert guard.require_version_match("/b.py", "bb") is None


class TestFileIntegrityGuardAgentAware:
    """Agent-aware isolation tests for concurrent subagent scenarios."""

    def test_different_agents_independent_reads(self) -> None:
        guard = FileIntegrityGuard()
        guard.record_read("/f.py", "v1", agent_id="agent-a")
        guard.record_read("/f.py", "v1", agent_id="agent-b")
        assert guard.require_version_match("/f.py", "modified", agent_id="agent-a") is not None
        assert guard.require_version_match("/f.py", "modified", agent_id="agent-b") is not None

    def test_agent_write_does_not_mask_other_agent(self) -> None:
        guard = FileIntegrityGuard()
        guard.record_read("/f.py", "v1", agent_id="agent-a")
        guard.record_read("/f.py", "v1", agent_id="agent-b")
        guard.record_write("/f.py", "v2", agent_id="agent-a")
        assert guard.require_version_match("/f.py", "v2", agent_id="agent-a") is None
        assert guard.require_version_match("/f.py", "v2", agent_id="agent-b") is not None

    def test_clear_agent_removes_one_agent_only(self) -> None:
        guard = FileIntegrityGuard()
        guard.record_read("/f.py", "v1", agent_id="agent-a")
        guard.record_read("/f.py", "v1", agent_id="agent-b")
        guard.clear_agent("agent-a")
        assert guard.require_version_match("/f.py", "changed", agent_id="agent-a") is None
        assert guard.require_version_match("/f.py", "changed", agent_id="agent-b") is not None

    def test_clear_removes_all_agents(self) -> None:
        guard = FileIntegrityGuard()
        guard.record_read("/f.py", "v1", agent_id="agent-a")
        guard.record_read("/f.py", "v1", agent_id="agent-b")
        guard.clear()
        assert guard.require_version_match("/f.py", "changed", agent_id="agent-a") is None
        assert guard.require_version_match("/f.py", "changed", agent_id="agent-b") is None

    def test_default_agent_id_when_no_context(self) -> None:
        guard = FileIntegrityGuard()
        guard.record_read("/f.py", "v1")
        assert guard.require_version_match("/f.py", "v1") is None
        assert guard.require_version_match("/f.py", "changed") is not None

    def test_clear_agent_nonexistent_is_safe(self) -> None:
        guard = FileIntegrityGuard()
        guard.clear_agent("does-not-exist")

    def test_reread_updates_hash(self) -> None:
        guard = FileIntegrityGuard()
        guard.record_read("/f.py", "v1", agent_id="a")
        guard.record_read("/f.py", "v2", agent_id="a")
        assert guard.require_version_match("/f.py", "v2", agent_id="a") is None
        assert guard.require_version_match("/f.py", "v1", agent_id="a") is not None

    def test_unread_agent_returns_none(self) -> None:
        guard = FileIntegrityGuard()
        guard.record_read("/f.py", "v1", agent_id="a")
        assert guard.require_version_match("/f.py", "anything", agent_id="b") is None


class TestGetFileIntegrityGuard:
    """Module-level factory function tests."""

    def test_returns_none_for_no_executor(self) -> None:
        assert get_file_integrity_guard(None) is None

    def test_returns_guard_for_executor(self) -> None:
        executor = MagicMock()
        guard = get_file_integrity_guard(executor)
        assert guard is not None
        assert isinstance(guard, FileIntegrityGuard)

    def test_same_executor_same_guard(self) -> None:
        executor = MagicMock()
        g1 = get_file_integrity_guard(executor)
        g2 = get_file_integrity_guard(executor)
        assert g1 is g2

    def test_different_executors_different_guards(self) -> None:
        e1 = MagicMock()
        e2 = MagicMock()
        g1 = get_file_integrity_guard(e1)
        g2 = get_file_integrity_guard(e2)
        assert g1 is not g2

    def teardown_method(self) -> None:
        _integrity_guards.clear()


class TestReadBeforeEditGate:
    """Tests for the read-before-edit gate (require_read_before_write)."""

    def test_gate_blocks_unread_file(self) -> None:
        guard = FileIntegrityGuard()
        rejection = guard.require_read_before_write("/unread.py")
        assert rejection is not None
        assert "has not been read" in rejection

    def test_gate_passes_after_full_read(self) -> None:
        guard = FileIntegrityGuard()
        guard.record_read("/a.py", "content")
        assert guard.require_read_before_write("/a.py") is None

    def test_gate_passes_after_partial_read(self) -> None:
        guard = FileIntegrityGuard()
        guard.record_read_marker("/a.py")
        assert guard.require_read_before_write("/a.py") is None

    def test_gate_passes_after_write(self) -> None:
        guard = FileIntegrityGuard()
        guard.record_write("/a.py", "content")
        assert guard.require_read_before_write("/a.py") is None

    def test_gate_blocks_after_clear(self) -> None:
        guard = FileIntegrityGuard()
        guard.record_read("/a.py", "content")
        guard.clear()
        rejection = guard.require_read_before_write("/a.py")
        assert rejection is not None

    def test_gate_agent_isolation(self) -> None:
        guard = FileIntegrityGuard()
        guard.record_read("/a.py", "content", agent_id="agent-a")
        assert guard.require_read_before_write("/a.py", agent_id="agent-a") is None
        rejection = guard.require_read_before_write("/a.py", agent_id="agent-b")
        assert rejection is not None

    def test_gate_path_normalization(self) -> None:
        guard = FileIntegrityGuard()
        guard.record_read("./dir/../a.py", "content")
        assert guard.require_read_before_write("a.py") is None


class TestFullReadBeforeEditGate:
    """Tests for full-read gate before edits (require_full_read_before_edit)."""

    def test_blocks_partial_read_only(self) -> None:
        guard = FileIntegrityGuard()
        guard.record_read_marker("/a.py")
        rejection = guard.require_full_read_before_edit("/a.py")
        assert rejection is not None
        assert "only partially read" in rejection

    def test_passes_after_full_read(self) -> None:
        guard = FileIntegrityGuard()
        guard.record_read("/a.py", "content")
        assert guard.require_full_read_before_edit("/a.py") is None

    def test_passes_after_write(self) -> None:
        guard = FileIntegrityGuard()
        guard.record_write("/a.py", "content")
        assert guard.require_full_read_before_edit("/a.py") is None


class TestRecordReadMarker:
    """Tests for partial read marker (record_read_marker)."""

    def test_marker_does_not_overwrite_full_hash(self) -> None:
        guard = FileIntegrityGuard()
        guard.record_read("/a.py", "full_content")
        guard.record_read_marker("/a.py")
        rejection = guard.require_version_match("/a.py", "changed")
        assert rejection is not None

    def test_marker_skips_version_check(self) -> None:
        guard = FileIntegrityGuard()
        guard.record_read_marker("/a.py")
        assert guard.require_version_match("/a.py", "anything") is None

    def test_full_read_upgrades_marker(self) -> None:
        guard = FileIntegrityGuard()
        guard.record_read_marker("/a.py")
        guard.record_read("/a.py", "full_content")
        assert guard.require_version_match("/a.py", "full_content") is None
        assert guard.require_version_match("/a.py", "different") is not None

    def test_marker_agent_isolation(self) -> None:
        guard = FileIntegrityGuard()
        guard.record_read_marker("/a.py", agent_id="agent-a")
        assert guard.require_read_before_write("/a.py", agent_id="agent-a") is None
        rejection = guard.require_read_before_write("/a.py", agent_id="agent-b")
        assert rejection is not None


class TestEdgeCases:
    """Edge case scenarios for completeness."""

    def test_empty_file_content_does_not_conflict_with_sentinel(self) -> None:
        guard = FileIntegrityGuard()
        guard.record_read("/empty.py", "")
        rejection = guard.require_version_match("/empty.py", "now has content")
        assert rejection is not None
        assert guard.require_version_match("/empty.py", "") is None

    def test_gate_passes_after_create_then_edit(self) -> None:
        guard = FileIntegrityGuard()
        guard.record_write("/new.py", "initial content")
        assert guard.require_read_before_write("/new.py") is None

    def test_clear_agent_then_other_agent_unaffected(self) -> None:
        guard = FileIntegrityGuard()
        guard.record_read("/f.py", "v1", agent_id="a")
        guard.record_read("/f.py", "v1", agent_id="b")
        guard.clear_agent("a")
        assert guard.require_read_before_write("/f.py", agent_id="a") is not None
        assert guard.require_read_before_write("/f.py", agent_id="b") is None

    def test_version_after_partial_read_then_full_read(self) -> None:
        guard = FileIntegrityGuard()
        guard.record_read_marker("/f.py")
        guard.record_read("/f.py", "full content v1")
        assert guard.require_version_match("/f.py", "full content v1") is None
        assert guard.require_version_match("/f.py", "modified") is not None

    def test_multiple_writes_update_hash(self) -> None:
        guard = FileIntegrityGuard()
        guard.record_read("/f.py", "v1")
        guard.record_write("/f.py", "v2")
        guard.record_write("/f.py", "v3")
        assert guard.require_version_match("/f.py", "v3") is None
        assert guard.require_version_match("/f.py", "v2") is not None
