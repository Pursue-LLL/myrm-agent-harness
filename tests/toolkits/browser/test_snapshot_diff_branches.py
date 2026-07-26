"""Tests for snapshot_diff.py uncovered branches: render_diff, fold threshold, reset, generate_diff."""

from __future__ import annotations

from dataclasses import dataclass

from myrm_agent_harness.toolkits.browser.session.snapshot_diff import SnapshotDiffEngine


@dataclass
class FakeRefInfo:
    role: str
    name: str


class TestSnapshotDiffEngine:
    def test_reset_clears_state(self) -> None:
        engine = SnapshotDiffEngine()
        engine.update_baseline("line1\nline2", {"e1": FakeRefInfo("button", "Submit")})
        assert engine.has_baseline()
        engine.reset()
        assert not engine.has_baseline()

    def test_has_baseline_empty(self) -> None:
        engine = SnapshotDiffEngine()
        assert not engine.has_baseline()

    def test_has_baseline_after_update(self) -> None:
        engine = SnapshotDiffEngine()
        engine.update_baseline("line1", {})
        assert engine.has_baseline()

    def test_generate_diff_insert_delete(self) -> None:
        engine = SnapshotDiffEngine()
        engine.update_baseline("line1\nline2\nline3", {})
        result = engine.generate_diff("line1\nlineNew\nline3", {}, max_tokens=0, chars_per_token=4)
        assert "+" in result or "-" in result

    def test_generate_diff_replace(self) -> None:
        engine = SnapshotDiffEngine()
        engine.update_baseline("old_content", {})
        result = engine.generate_diff("new_content", {}, max_tokens=0, chars_per_token=4)
        assert "+" in result

    def test_generate_diff_no_change(self) -> None:
        engine = SnapshotDiffEngine()
        engine.update_baseline("same\ncontent", {})
        result = engine.generate_diff("same\ncontent", {}, max_tokens=0, chars_per_token=4)
        assert "diff" in result.lower()

    def test_generate_diff_fold_long_equal(self) -> None:
        lines = "\n".join(f"line{i}" for i in range(20))
        engine = SnapshotDiffEngine()
        engine.update_baseline(lines, {})
        new_lines = "new_first\n" + "\n".join(f"line{i}" for i in range(1, 20))
        result = engine.generate_diff(new_lines, {}, max_tokens=0, chars_per_token=4)
        assert "unchanged" in result

    def test_generate_diff_interactive_changes(self) -> None:
        engine = SnapshotDiffEngine()
        old_refs = {"e1": FakeRefInfo("button", "Submit"), "e2": FakeRefInfo("link", "Home")}
        engine.update_baseline("button Submit\nlink Home", old_refs)
        new_refs = {"e3": FakeRefInfo("button", "Submit"), "e4": FakeRefInfo("button", "New")}
        result = engine.generate_diff("button Submit\nbutton New", new_refs, max_tokens=0, chars_per_token=4)
        assert "New interactive" in result or "Removed interactive" in result

    def test_generate_diff_unchanged_interactive(self) -> None:
        engine = SnapshotDiffEngine()
        old_refs = {"e1": FakeRefInfo("button", "OK")}
        engine.update_baseline("button OK", old_refs)
        new_refs = {"e2": FakeRefInfo("button", "OK")}
        result = engine.generate_diff("button OK\nnew line", new_refs, max_tokens=0, chars_per_token=4)
        assert "Unchanged interactive" in result

    def test_calculate_fold_threshold_zero_max_tokens(self) -> None:
        engine = SnapshotDiffEngine()
        threshold = engine._calculate_fold_threshold(0, 100)
        assert threshold == 3  # _DIFF_FOLD_THRESHOLD

    def test_calculate_fold_threshold_under_budget(self) -> None:
        engine = SnapshotDiffEngine()
        threshold = engine._calculate_fold_threshold(1000, 500)
        assert threshold == 3

    def test_calculate_fold_threshold_over_budget(self) -> None:
        engine = SnapshotDiffEngine()
        threshold = engine._calculate_fold_threshold(100, 10000)
        assert threshold >= 3
        assert threshold <= 50
