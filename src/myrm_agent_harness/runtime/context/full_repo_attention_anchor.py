"""Attention anchor injection and AST drift tolerance aligner for 1M context.

Mitigates Lost-in-the-Middle attention decay and resolves line drift
discrepancies during full-repo multi-file refactoring.
"""

import re

from myrm_agent_harness.runtime.context.full_repo_refactor_types import (
    RepoAstTopology,
    SemanticAnchor,
)


class AttentionAnchorInjector:
    """Injects high-fan-in semantic anchors to prevent Lost-in-the-Middle decay."""

    def __init__(self, min_fan_in: int = 2) -> None:
        self._min_fan_in = min_fan_in

    def extract_semantic_anchors(
        self, topology: RepoAstTopology
    ) -> list[SemanticAnchor]:
        """Identify critical shared symbols across modules and construct anchors."""
        anchors: list[SemanticAnchor] = []
        fan_in_counts: dict[str, list[str]] = {}

        # Aggregate callers for each file
        for caller_file, callees in topology.cross_file_dependencies.items():
            for callee_file in callees:
                if callee_file not in fan_in_counts:
                    fan_in_counts[callee_file] = []
                fan_in_counts[callee_file].append(caller_file)

        # Generate anchors for files with high fan-in
        anchor_idx = 1
        for file_path, callers in sorted(
            fan_in_counts.items(), key=lambda x: len(x[1]), reverse=True
        ):
            if len(callers) < self._min_fan_in:
                continue
            node = topology.file_nodes.get(file_path)
            if not node or not node.symbols:
                continue

            for sym in node.symbols:
                anchor_id = f"ANC-{anchor_idx:03d}-{sym.name}"
                hint = (
                    f"Core hub `{sym.name}` in `{file_path}:{sym.line_number}` "
                    f"referenced across {len(callers)} modules: "
                    f"{', '.join(sorted(callers)[:3])}. Ensure cross-file consistency."
                )
                anchors.append(
                    SemanticAnchor(
                        anchor_id=anchor_id,
                        symbol_name=sym.name,
                        file_path=file_path,
                        definition_line=sym.line_number,
                        fan_in_references=sorted(callers),
                        prompt_hint=hint,
                    )
                )
                anchor_idx += 1
                if len(anchors) >= 20:  # Bound to top 20 most critical anchors
                    break
            if len(anchors) >= 20:
                break

        return anchors

    def render_anchors_block(self, anchors: list[SemanticAnchor]) -> str:
        """Format anchors into a prominent attention refocusing prompt block."""
        if not anchors:
            return ""

        lines: list[str] = [
            "<!-- SEMANTIC ATTENTION ANCHORS (LOST-IN-THE-MIDDLE MITIGATION) -->",
            "<attention_anchors>",
        ]
        for a in anchors:
            refs = ", ".join(a.fan_in_references)
            lines.append(
                f'  <anchor id="{a.anchor_id}" symbol="{a.symbol_name}" '
                f'file="{a.file_path}" line="{a.definition_line}" fan_in="{refs}">'
            )
            lines.append(f"    {a.prompt_hint}")
            lines.append("  </anchor>")
        lines.append("</attention_anchors>")
        return "\n".join(lines)


class AstDriftToleranceAligner:
    """Resolves code drift and whitespace fluctuations when applying refactor diffs."""

    def __init__(self, search_window_lines: int = 50) -> None:
        self._window_lines = search_window_lines

    def find_target_slice(
        self,
        full_content: str,
        target_snippet: str,
        line_hint: int | None = None,
        symbol_anchor_name: str | None = None,
    ) -> tuple[int, int] | None:
        """Locate exact character boundaries (start, end) for replacement with drift tolerance."""
        if not target_snippet:
            return None

        # 1. Exact direct match
        exact_pos = full_content.find(target_snippet)
        if exact_pos != -1:
            # Ensure it's unique or best positioned if line_hint provided
            if line_hint is None:
                return (exact_pos, exact_pos + len(target_snippet))
            else:
                occurrences = self._all_occurrences(
                    full_content, target_snippet
                )
                best_occ = self._select_closest_to_line(
                    full_content, occurrences, line_hint
                )
                return (best_occ, best_occ + len(target_snippet))

        # 2. Symbol-anchored local search
        if symbol_anchor_name:
            symbol_pattern = re.compile(
                rf"(class|def|function|const|let|var)\s+{re.escape(symbol_anchor_name)}\b"
            )
            match = symbol_pattern.search(full_content)
            if match:
                sym_start = match.start()
                sym_sub = full_content[sym_start : sym_start + 5000]
                fuzzy_sub_pos = self._fuzzy_match(sym_sub, target_snippet)
                if fuzzy_sub_pos is not None:
                    actual_start = sym_start + fuzzy_sub_pos[0]
                    actual_end = sym_start + fuzzy_sub_pos[1]
                    return (actual_start, actual_end)

        # 3. Line-hint bounded fuzzy window search
        if line_hint is not None:
            lines = full_content.splitlines(keepends=True)
            hint_0 = max(0, line_hint - 1)
            win_start = max(0, hint_0 - self._window_lines)
            win_end = min(len(lines), hint_0 + self._window_lines)

            sub_text = "".join(lines[win_start:win_end])
            char_offset = sum(len(line) for line in lines[:win_start])
            res = self._fuzzy_match(sub_text, target_snippet)
            if res is not None:
                return (char_offset + res[0], char_offset + res[1])

        # 4. Global whitespace-normalized fallback
        return self._fuzzy_match(full_content, target_snippet)

    def _all_occurrences(self, text: str, sub: str) -> list[int]:
        res: list[int] = []
        pos = 0
        while True:
            idx = text.find(sub, pos)
            if idx == -1:
                break
            res.append(idx)
            pos = idx + 1
        return res

    def _select_closest_to_line(
        self, text: str, occurrences: list[int], target_line: int
    ) -> int:
        if not occurrences:
            return 0
        best_pos = occurrences[0]
        min_dist = float("inf")
        for pos in occurrences:
            line_no = text[:pos].count("\n") + 1
            dist = abs(line_no - target_line)
            if dist < min_dist:
                min_dist = dist
                best_pos = pos
        return best_pos

    def _fuzzy_match(
        self, haystack: str, needle: str
    ) -> tuple[int, int] | None:
        """Match ignoring trailing/leading line whitespace while preserving core structure."""
        needle_clean = self._normalize_lines(needle)
        if not needle_clean:
            return None

        haystack_lines = haystack.splitlines(keepends=True)
        needle_lines = needle.strip().splitlines()
        needle_len = len(needle_lines)

        if needle_len == 0:
            return None

        for i in range(len(haystack_lines) - needle_len + 1):
            window = [hl.strip() for hl in haystack_lines[i : i + needle_len]]
            target = [nl.strip() for nl in needle_lines]
            if window == target:
                start_char = sum(len(line) for line in haystack_lines[:i])
                matched_chars = sum(
                    len(line) for line in haystack_lines[i : i + needle_len]
                )
                return (start_char, start_char + matched_chars)

        return None

    def _normalize_lines(self, s: str) -> str:
        return "\n".join(line.strip() for line in s.splitlines() if line.strip())
