"""Tests for invariant_snapshot: capture, verify, clear lifecycle."""

from __future__ import annotations

import os

import pytest

from myrm_agent_harness.agent.goals.invariant_snapshot import (
    ProtectedFileViolation,
    _snapshots,
    capture_protected_snapshot,
    clear_snapshot,
    verify_protected_integrity,
)


@pytest.fixture(autouse=True)
def _clean_snapshots():
    _snapshots.clear()
    yield
    _snapshots.clear()


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("assert True")
    (tmp_path / "tests" / "test_b.py").write_text("assert False")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')")
    return str(tmp_path)


class TestCaptureProtectedSnapshot:
    def test_captures_matching_files(self, workspace: str):
        count = capture_protected_snapshot("g1", ["tests/**"], workspace)
        assert count == 2
        assert "g1" in _snapshots

    def test_empty_patterns_returns_zero(self, workspace: str):
        count = capture_protected_snapshot("g2", [], workspace)
        assert count == 0
        assert "g2" not in _snapshots

    def test_no_matching_files(self, workspace: str):
        count = capture_protected_snapshot("g3", ["nonexistent/**"], workspace)
        assert count == 0

    def test_overwrites_previous_snapshot(self, workspace: str):
        capture_protected_snapshot("g1", ["tests/**"], workspace)
        capture_protected_snapshot("g1", ["src/**"], workspace)
        _, patterns, _ = _snapshots["g1"]
        assert patterns == ["src/**"]


class TestVerifyProtectedIntegrity:
    def test_no_snapshot_returns_empty(self):
        assert verify_protected_integrity("nonexistent") == []

    def test_intact_files_return_empty(self, workspace: str):
        capture_protected_snapshot("g1", ["tests/**"], workspace)
        violations = verify_protected_integrity("g1")
        assert violations == []
        assert "g1" in _snapshots  # non-destructive: snapshot preserved for repeated verify

    def test_detects_modified_file(self, workspace: str):
        capture_protected_snapshot("g1", ["tests/**"], workspace)
        with open(os.path.join(workspace, "tests", "test_a.py"), "w") as f:
            f.write("TAMPERED")
        violations = verify_protected_integrity("g1")
        assert len(violations) == 1
        assert violations[0].kind == "modified"
        assert "test_a.py" in violations[0].path

    def test_detects_deleted_file(self, workspace: str):
        capture_protected_snapshot("g1", ["tests/**"], workspace)
        os.remove(os.path.join(workspace, "tests", "test_b.py"))
        violations = verify_protected_integrity("g1")
        assert len(violations) == 1
        assert violations[0].kind == "deleted"

    def test_detects_created_file(self, workspace: str):
        capture_protected_snapshot("g1", ["tests/**"], workspace)
        with open(os.path.join(workspace, "tests", "test_c.py"), "w") as f:
            f.write("new file")
        violations = verify_protected_integrity("g1")
        assert len(violations) == 1
        assert violations[0].kind == "created"

    def test_multiple_violations(self, workspace: str):
        capture_protected_snapshot("g1", ["tests/**"], workspace)
        with open(os.path.join(workspace, "tests", "test_a.py"), "w") as f:
            f.write("TAMPERED")
        os.remove(os.path.join(workspace, "tests", "test_b.py"))
        violations = verify_protected_integrity("g1")
        assert len(violations) == 2
        kinds = {v.kind for v in violations}
        assert kinds == {"modified", "deleted"}

    def test_verify_preserves_snapshot(self, workspace: str):
        capture_protected_snapshot("g1", ["tests/**"], workspace)
        verify_protected_integrity("g1")
        assert "g1" in _snapshots  # non-destructive; clear_snapshot handles cleanup

    def test_repeated_verify_detects_tamper(self, workspace: str):
        capture_protected_snapshot("g1", ["tests/**"], workspace)
        assert verify_protected_integrity("g1") == []
        with open(os.path.join(workspace, "tests", "test_a.py"), "w") as f:
            f.write("TAMPERED")
        violations = verify_protected_integrity("g1")
        assert len(violations) == 1
        assert violations[0].kind == "modified"


class TestClearSnapshot:
    def test_clears_existing(self, workspace: str):
        capture_protected_snapshot("g1", ["tests/**"], workspace)
        clear_snapshot("g1")
        assert "g1" not in _snapshots

    def test_noop_on_missing(self):
        clear_snapshot("nonexistent")  # should not raise


class TestProtectedFileViolation:
    def test_dataclass_frozen(self):
        v = ProtectedFileViolation(path="/a/b.py", pattern="tests/**", kind="modified")
        with pytest.raises(AttributeError):
            v.path = "/other"  # type: ignore[misc]
