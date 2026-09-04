"""Semantic line-level diff for ARIA snapshot text with Myers optimization.

Normalizes ref prefixes (e.g. ``e3:``) and inline IDs before comparing so that
unchanged ARIA content is folded, while interactive element additions/removals
are reported explicitly. Incorporates Identical Inputs Fast Path, adaptive full
snapshot fallback for large page shifts, and ancestor container breadcrumb preservation.

[INPUT]
- toolkits.browser.snapshot::RefInfo (POS: browser_snapshot tool for ARIA tree capture.)

[OUTPUT]
- DiffOutput: immutable structured result of diff calculation.
- SnapshotDiffEngine: maintains baseline and generates optimized diff output.
"""

from __future__ import annotations

import dataclasses
import difflib
import hashlib
import logging
import re
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.browser.snapshot import RefInfo

logger = logging.getLogger(__name__)

_REF_PREFIX_RE = re.compile(r"^(\s*)(?:f\d+_)?e\d+[:\s]\s*")
_DIFF_FOLD_THRESHOLD = 3
_MAX_UNCHANGED_DISPLAY = 10
_MAX_LINE_CHARS = 500
_FALLBACK_DIFF_RATIO = 0.6
_MIN_FALLBACK_LINES = 10
_MIN_FALLBACK_CHANGES = 6
_CONTAINER_KEYWORDS = (
    "[dialog",
    "[modal",
    "[form",
    "[main",
    "[navigation",
    "[region",
    "[group",
    "[alertdialog",
    "[drawer",
    "[sheet",
)
_IDENTICAL_NOTICE = "=== Snapshot diff: No DOM changes detected since last snapshot ==="


@dataclasses.dataclass(frozen=True)
class DiffOutput:
    """Structured result of semantic ARIA snapshot diff."""

    diff_text: str
    is_identical: bool = False
    additions: int = 0
    removals: int = 0
    unchanged: int = 0
    is_fallback_full: bool = False
    tokens_saved: int = 0


class SnapshotDiffEngine:
    """Maintains snapshot text baseline and generates normalized line-level diffs."""

    def __init__(self) -> None:
        self._prev_normalized: list[str] = []
        self._prev_original: list[str] = []
        self._prev_ref_map: dict[tuple[str, str], tuple[str, str]] = {}
        self._prev_hash: str = ""
        self._normalization_cache: dict[str, str] = {}

    def reset(self) -> None:
        self._prev_normalized.clear()
        self._prev_original.clear()
        self._prev_ref_map.clear()
        self._prev_hash = ""
        self._normalization_cache.clear()

    def has_baseline(self) -> bool:
        return len(self._prev_normalized) > 0

    def _normalize_line(self, line: str) -> str:
        if line not in self._normalization_cache:
            norm = _REF_PREFIX_RE.sub(r"\1", line)
            if len(norm) > _MAX_LINE_CHARS:
                norm = f"{norm[:_MAX_LINE_CHARS]} ...[truncated]"
            self._normalization_cache[line] = norm
        return self._normalization_cache[line]

    def _normalize_lines(self, lines: list[str]) -> list[str]:
        return [self._normalize_line(line) for line in lines]

    @staticmethod
    def _compute_hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _track_interactive_changes(
        self, prev_refs: dict[tuple[str, str], tuple[str, str]], current_refs: dict[str, RefInfo]
    ) -> tuple[list[str], list[str], list[str]]:
        current_ref_sigs = {(r.role, r.name) for r in current_refs.values()}

        new_interactive = [
            f'{ref_id} ({info.role} "{info.name}")'
            for ref_id, info in current_refs.items()
            if (info.role, info.name) not in prev_refs
        ]

        removed_interactive = [
            f'({role} "{name}")' for (role, name) in prev_refs if (role, name) not in current_ref_sigs
        ]

        unchanged_interactive = [ref_id for ref_id, info in current_refs.items() if (info.role, info.name) in prev_refs]

        return new_interactive, removed_interactive, unchanged_interactive

    def _calculate_fold_threshold(self, max_tokens: int, estimated_tokens: int) -> int:
        if max_tokens == 0:
            return _DIFF_FOLD_THRESHOLD

        tokens_to_save = estimated_tokens - max_tokens
        if tokens_to_save <= 0:
            return _DIFF_FOLD_THRESHOLD

        lines_to_fold = tokens_to_save // 20
        threshold = max(_DIFF_FOLD_THRESHOLD, lines_to_fold // 10)
        return min(threshold, 50)

    @staticmethod
    def _find_ancestor_anchor(prev_lines: list[str], start_idx: int, end_idx: int) -> str | None:
        """Find the most relevant semantic container in a folded unchanged block."""
        for idx in range(end_idx - 1, start_idx - 1, -1):
            line = prev_lines[idx].strip()
            if any(keyword in line.lower() for keyword in _CONTAINER_KEYWORDS):
                return prev_lines[idx]
        return None

    def _render_diff(
        self,
        opcodes: list[tuple[str, int, int, int, int]],
        prev_lines: list[str],
        current_lines: list[str],
        interactive_changes: tuple[list[str], list[str], list[str]],
        fold_threshold: int,
    ) -> tuple[str, int, int, int]:
        diff_lines = ["--- Snapshot diff ---"]
        added_count = 0
        removed_count = 0
        unchanged_count = 0

        for tag, i1, i2, j1, j2 in opcodes:
            if tag == "equal":
                num_lines = i2 - i1
                unchanged_count += num_lines
                if num_lines > fold_threshold:
                    diff_lines.append(f"  {prev_lines[i1]}")
                    anchor = self._find_ancestor_anchor(prev_lines, i1 + 1, i2 - 1)
                    if anchor and anchor != prev_lines[i1] and anchor != prev_lines[i2 - 1]:
                        diff_lines.append(f"  ... ({num_lines - 3} unchanged lines) ...")
                        diff_lines.append(f"  {anchor}")
                    else:
                        diff_lines.append(f"  ... ({num_lines - 2} unchanged lines) ...")
                    diff_lines.append(f"  {prev_lines[i2 - 1]}")
                else:
                    for i in range(i1, i2):
                        diff_lines.append(f"  {prev_lines[i]}")
            elif tag == "delete":
                for i in range(i1, i2):
                    diff_lines.append(f"- {prev_lines[i]}")
                    removed_count += 1
            elif tag == "insert":
                for j in range(j1, j2):
                    diff_lines.append(f"+ {current_lines[j]}")
                    added_count += 1
            elif tag == "replace":
                for i in range(i1, i2):
                    diff_lines.append(f"- {prev_lines[i]}")
                    removed_count += 1
                for j in range(j1, j2):
                    diff_lines.append(f"+ {current_lines[j]}")
                    added_count += 1

        new_interactive, removed_interactive, unchanged_interactive = interactive_changes

        if new_interactive:
            diff_lines.append(f"--- New interactive: {', '.join(new_interactive)} ---")
        if removed_interactive:
            diff_lines.append(f"--- Removed interactive: {', '.join(removed_interactive)} ---")
        if unchanged_interactive:
            display_count = min(len(unchanged_interactive), _MAX_UNCHANGED_DISPLAY)
            diff_lines.append(f"--- Unchanged interactive: {', '.join(unchanged_interactive[:display_count])} ---")

        return "\n".join(diff_lines), added_count, removed_count, unchanged_count

    def compute_diff(
        self, current_tree: str, current_refs: dict[str, RefInfo], max_tokens: int, chars_per_token: int
    ) -> DiffOutput:
        """Compute structured diff against previous baseline."""
        start_time = time.time()
        current_hash = self._compute_hash(current_tree)

        # 1. Identical Fast Path (0ms, 0 token waste)
        if self._prev_hash and current_hash == self._prev_hash:
            tokens_saved = max(0, (len(current_tree) - len(_IDENTICAL_NOTICE)) // chars_per_token)
            return DiffOutput(
                diff_text=_IDENTICAL_NOTICE,
                is_identical=True,
                additions=0,
                removals=0,
                unchanged=len(self._prev_original),
                is_fallback_full=False,
                tokens_saved=tokens_saved,
            )

        current_lines = current_tree.split("\n")
        current_normalized = self._normalize_lines(current_lines)

        # Fast path 2: Normalized lines identical (e.g. only ref IDs shifted)
        if self._prev_normalized and current_normalized == self._prev_normalized:
            tokens_saved = max(0, (len(current_tree) - len(_IDENTICAL_NOTICE)) // chars_per_token)
            return DiffOutput(
                diff_text=_IDENTICAL_NOTICE,
                is_identical=True,
                additions=0,
                removals=0,
                unchanged=len(self._prev_original),
                is_fallback_full=False,
                tokens_saved=tokens_saved,
            )

        matcher = difflib.SequenceMatcher(None, self._prev_normalized, current_normalized)
        opcodes = matcher.get_opcodes()

        estimated_tokens = len(current_tree) // chars_per_token
        fold_threshold = self._calculate_fold_threshold(max_tokens, estimated_tokens)
        interactive_changes = self._track_interactive_changes(self._prev_ref_map, current_refs)

        diff_text, added_count, removed_count, unchanged_count = self._render_diff(
            opcodes, self._prev_original, current_lines, interactive_changes, fold_threshold
        )

        # 2. Adaptive Diff Fallback Circuit Breaker
        prev_len = len(self._prev_original)
        total_changes = added_count + removed_count
        if (
            prev_len >= _MIN_FALLBACK_LINES
            and total_changes >= _MIN_FALLBACK_CHANGES
            and (total_changes / prev_len > _FALLBACK_DIFF_RATIO)
        ):
            logger.info(
                f"Adaptive diff fallback triggered: change ratio ({total_changes / prev_len:.2f}) "
                f"> {_FALLBACK_DIFF_RATIO}. Returning full snapshot to preserve context."
            )
            return DiffOutput(
                diff_text=current_tree,
                is_identical=False,
                additions=added_count,
                removals=removed_count,
                unchanged=unchanged_count,
                is_fallback_full=True,
                tokens_saved=0,
            )

        elapsed = time.time() - start_time
        if elapsed > 0.1:
            logger.warning(
                f"Diff generation slow: {elapsed * 1000:.2f}ms for {len(current_lines)} lines "
                f"(+{added_count} -{removed_count})"
            )

        tokens_saved = max(0, (len(current_tree) - len(diff_text)) // chars_per_token)
        return DiffOutput(
            diff_text=diff_text,
            is_identical=False,
            additions=added_count,
            removals=removed_count,
            unchanged=unchanged_count,
            is_fallback_full=False,
            tokens_saved=tokens_saved,
        )

    def generate_diff(
        self, current_tree: str, current_refs: dict[str, RefInfo], max_tokens: int, chars_per_token: int
    ) -> str:
        """Backward-compatible string output delegating to compute_diff."""
        output = self.compute_diff(current_tree, current_refs, max_tokens, chars_per_token)
        return output.diff_text

    def update_baseline(self, aria_tree: str, refs: dict[str, RefInfo]) -> None:
        lines = aria_tree.split("\n")
        self._prev_original = lines
        self._prev_normalized = [self._normalize_line(line) for line in lines]
        self._prev_ref_map = {(r.role, r.name): (ref_id, r.role) for ref_id, r in refs.items()}
        self._prev_hash = self._compute_hash(aria_tree)
