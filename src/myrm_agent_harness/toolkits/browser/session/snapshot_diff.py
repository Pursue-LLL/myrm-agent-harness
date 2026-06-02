"""ARIA snapshottext'ssemantic diff(ref prefixnormalizeafterlinelevelfor).

implementationtype: `SnapshotDiffEngine`.and `SnapshotManager` coordinatemaintainsbaselineandgenerates diff output.

[INPUT]
- toolkits.browser.snapshot::RefInfo (POS: browser_snapshot tool for ARIA tree capture.)

[OUTPUT]
- SnapshotDiffEngine: maintainssnapshottextbaselineandgeneratesnormalizeresulti...

[POS]
ARIA snapshottext'ssemantic diff(ref prefixnormalizeafterlinelevelfor).
"""

from __future__ import annotations

import difflib
import logging
import re
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.browser.snapshot import RefInfo

logger = logging.getLogger(__name__)

_REF_PREFIX_RE = re.compile(r"^(?:f\d+_)?e\d+[:\s]")
_DIFF_FOLD_THRESHOLD = 3
_MAX_UNCHANGED_DISPLAY = 10


class SnapshotDiffEngine:
    """maintainssnapshottextbaselineandgeneratesnormalizeresultinglinelevel diff."""

    def __init__(self) -> None:
        self._prev_normalized: list[str] = []
        self._prev_original: list[str] = []
        self._prev_ref_map: dict[tuple[str, str], tuple[str, str]] = {}
        self._normalization_cache: dict[str, str] = {}

    def reset(self) -> None:
        self._prev_normalized.clear()
        self._prev_original.clear()
        self._prev_ref_map.clear()
        self._normalization_cache.clear()

    def has_baseline(self) -> bool:
        return len(self._prev_normalized) > 0

    def _normalize_line(self, line: str) -> str:
        if line not in self._normalization_cache:
            self._normalization_cache[line] = _REF_PREFIX_RE.sub("", line)
        return self._normalization_cache[line]

    def _normalize_lines(self, lines: list[str]) -> list[str]:
        return [self._normalize_line(line) for line in lines]

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

    def _render_diff(
        self,
        opcodes: list[tuple[str, int, int, int, int]],
        prev_lines: list[str],
        current_lines: list[str],
        interactive_changes: tuple[list[str], list[str], list[str]],
        fold_threshold: int,
    ) -> tuple[str, int, int]:
        diff_lines = ["--- Snapshot diff ---"]
        added_count = 0
        removed_count = 0

        for tag, i1, i2, j1, j2 in opcodes:
            if tag == "equal":
                num_lines = i2 - i1
                if num_lines > fold_threshold:
                    diff_lines.append(f"  {prev_lines[i1]}")
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

        return "\n".join(diff_lines), added_count, removed_count

    def generate_diff(
        self, current_tree: str, current_refs: dict[str, RefInfo], max_tokens: int, chars_per_token: int
    ) -> str:
        start_time = time.time()

        current_lines = current_tree.split("\n")
        current_normalized = self._normalize_lines(current_lines)

        matcher = difflib.SequenceMatcher(None, self._prev_normalized, current_normalized)
        opcodes = matcher.get_opcodes()

        estimated_tokens = len(current_tree) // chars_per_token
        fold_threshold = self._calculate_fold_threshold(max_tokens, estimated_tokens)

        interactive_changes = self._track_interactive_changes(self._prev_ref_map, current_refs)

        diff_text, added_count, removed_count = self._render_diff(
            opcodes, self._prev_original, current_lines, interactive_changes, fold_threshold
        )

        elapsed = time.time() - start_time
        if elapsed > 0.1:
            logger.warning(
                f"Diff generation slow: {elapsed * 1000:.2f}ms for {len(current_lines)} lines "
                f"(+{added_count} -{removed_count})"
            )

        return diff_text

    def update_baseline(self, aria_tree: str, refs: dict[str, RefInfo]) -> None:
        lines = aria_tree.split("\n")
        self._prev_original = lines
        self._prev_normalized = [self._normalize_line(line) for line in lines]
        self._prev_ref_map = {(r.role, r.name): (ref_id, r.role) for ref_id, r in refs.items()}
