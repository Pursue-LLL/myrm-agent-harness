"""Tests for snapshot_diff.py uncovered branches: render_diff, fold threshold, reset, generate_diff."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from myrm_agent_harness.toolkits.browser.session.snapshot_diff import (
    _IDENTICAL_NOTICE,
    DiffOutput,
    SnapshotDiffEngine,
)
from myrm_agent_harness.toolkits.browser.session.snapshot_result import SnapshotResult
from myrm_agent_harness.toolkits.browser.snapshot import SnapshotMeta


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

    def test_compute_diff_identical_fast_path(self) -> None:
        tree = "\n".join(f'  e{i}: [button] "Action Button {i}"' for i in range(25))
        engine = SnapshotDiffEngine()
        engine.update_baseline(tree, {})
        output = engine.compute_diff(tree, {}, max_tokens=0, chars_per_token=4)
        assert output.is_identical is True
        assert output.additions == 0
        assert output.removals == 0
        assert output.is_fallback_full is False
        assert output.diff_text == _IDENTICAL_NOTICE
        assert output.tokens_saved > 0

    def test_compute_diff_normalized_identical_fast_path(self) -> None:
        baseline_tree = "\n".join(f'  e{i}: [button] "Item {i}"' for i in range(25))
        current_tree = "\n".join(f'  e{i + 50}: [button] "Item {i}"' for i in range(25))
        engine = SnapshotDiffEngine()
        engine.update_baseline(baseline_tree, {})
        output = engine.compute_diff(current_tree, {}, max_tokens=0, chars_per_token=4)
        assert output.is_identical is True
        assert output.diff_text == _IDENTICAL_NOTICE
        assert output.tokens_saved > 0

    def test_compute_diff_adaptive_fallback_large_page(self) -> None:
        baseline_lines = [f"line_{i}_content" for i in range(20)]
        baseline_tree = "\n".join(baseline_lines)
        engine = SnapshotDiffEngine()
        engine.update_baseline(baseline_tree, {})

        # Change 15 out of 20 lines (> 60% ratio on >= 10 lines)
        current_lines = [f"completely_different_line_{i}" for i in range(15)] + baseline_lines[15:]
        current_tree = "\n".join(current_lines)

        output = engine.compute_diff(current_tree, {}, max_tokens=0, chars_per_token=4)
        assert output.is_fallback_full is True
        assert output.is_identical is False
        assert output.diff_text == current_tree
        assert output.tokens_saved == 0

    def test_ancestor_container_breadcrumb_preservation(self) -> None:
        lines = [f"header_{i}" for i in range(3)]
        lines.append('  [dialog "User Profile Modal"]')
        lines.extend([f"content_body_{i}" for i in range(15)])
        lines.append("footer")
        baseline_tree = "\n".join(lines)

        engine = SnapshotDiffEngine()
        engine.update_baseline(baseline_tree, {})

        # Modify only the footer
        new_lines = list(lines)
        new_lines[-1] = "footer_updated"
        current_tree = "\n".join(new_lines)

        output = engine.compute_diff(current_tree, {}, max_tokens=0, chars_per_token=4)
        assert output.is_fallback_full is False
        # Ancestor dialog container should be preserved in folded region
        assert '[dialog "User Profile Modal"]' in output.diff_text
        assert "+ footer_updated" in output.diff_text

    def test_snapshot_result_structured_metrics(self) -> None:
        diff_out = DiffOutput(
            diff_text="--- Snapshot diff ---\n+ added line",
            is_identical=False,
            additions=1,
            removals=0,
            unchanged=5,
            is_fallback_full=False,
            tokens_saved=42,
        )
        meta = SnapshotMeta(ref_count=2, estimated_tokens=10)
        result = SnapshotResult(
            aria_tree="sample tree",
            refs=MappingProxyType({}),
            meta=meta,
            is_incremental=True,
            diff_output=diff_out,
        )
        assert result.is_identical is False
        assert result.additions == 1
        assert result.removals == 0
        assert result.tokens_saved == 42
        assert result.is_fallback_full is False

        # Verify tuple unpacking backward compatibility
        tree, meta_dict = result
        assert tree == "sample tree"
        assert meta_dict["ref_count"] == 2
        assert result.tree == "sample tree"

    def test_normalize_line_truncation_and_cache_cap(self) -> None:
        engine = SnapshotDiffEngine()
        # Truncation test
        long_line = "button " + "x" * 600
        norm = engine._normalize_line(long_line)
        assert norm.endswith("...[truncated]")
        assert len(norm) <= 520

        # Cache cap test (simulate filling cache beyond threshold)
        for i in range(2050):
            engine._normalize_line(f"line_{i}")
        assert len(engine._normalization_cache) <= 2048

    def test_generate_diff_pure_deletion(self) -> None:
        engine = SnapshotDiffEngine()
        baseline = "\n".join(f"line_{i}" for i in range(15))
        # Keep first 10 lines, remove last 5 (pure deletion)
        current = "\n".join(f"line_{i}" for i in range(10))
        engine.update_baseline(baseline, {})
        output = engine.compute_diff(current, {}, max_tokens=0, chars_per_token=4)
        assert output.removals == 5
        assert output.additions == 0
        assert "- line_14" in output.diff_text
