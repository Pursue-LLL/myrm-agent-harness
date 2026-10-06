"""Two-Phase Hard Anchors + Soft Context Scoring Diff Protocol (Pi Harness v2 Item 25 Part 2).

Implements robust model-generated unified diff application:
1. Hard Anchors Exact Matching (Phase 1):
   Extracts deletion (`-`) lines as absolute hard anchors to find candidate regions in the target file,
   eliminating fragile dependency on line numbers and hallucinated @@ range headers.
2. Soft Context Sliding-Window Scoring (Phase 1.5):
   When duplicate regions exist (e.g. repeated utility patterns or boilerplate), evaluates context
   (` `) lines above, below, and interleaved within candidates to uniquely disambiguate the target.
3. Non-Destructive Safe Patch Application & Drift Diagnostics (Phase 2):
   Reconstructs edits preserving original file indentation. If candidate matches tie or are missing,
   emits structured PatchDriftFinding diagnostics and rejects to prevent corrupting codebase.

[INPUT]
- operation: DiffOperation
- current: str
- exists: bool

[OUTPUT]
- find_hard_anchor_matches
- score_soft_context
- apply_diff_operation
- apply_diff_patch

[POS]
Harness runtime context & code execution layer. Robust content-addressed diff application engine.
"""

from __future__ import annotations

from myrm_agent_harness.runtime.context.diff_protocol_types import (
    DiffApplyResult,
    DiffHunk,
    DiffLine,
    DiffLineKind,
    DiffOperation,
    DiffProtocolError,
    PatchDriftFinding,
    parse_diff_operations,
)

__all__ = [
    "DiffApplyResult",
    "DiffHunk",
    "DiffLine",
    "DiffLineKind",
    "DiffOperation",
    "DiffProtocolError",
    "PatchDriftFinding",
    "apply_diff_operation",
    "apply_diff_patch",
    "find_hard_anchor_matches",
    "parse_diff_operations",
    "score_soft_context",
]


def _normal(line: str) -> str:
    """Normalize line for matching by stripping leading spaces and line endings."""
    return line.lstrip().rstrip("\r\n")


def find_hard_anchor_matches(file_lines: list[str], remove_lines: list[str]) -> list[int]:
    """Return every start index where remove_lines appear contiguously in file_lines."""
    if not remove_lines:
        return list(range(len(file_lines) + 1))
    needle = [_normal(ln) for ln in remove_lines]
    n = len(needle)
    return [
        start
        for start in range(len(file_lines) - n + 1)
        if [_normal(file_lines[start + i]) for i in range(n)] == needle
    ]


def score_soft_context(
    file_lines: list[str],
    candidate_start: int,
    candidate_end: int,
    hunk: DiffHunk,
) -> int:
    """Score how many context lines from hunk match file_lines around [candidate_start, candidate_end)."""
    above_ctx: list[str] = []
    below_ctx: list[str] = []
    inner_ctx: list[tuple[int, str]] = []

    last_remove_offset = -1
    tmp_offset = 0
    for dl in hunk.lines:
        if dl.kind == DiffLineKind.REMOVE:
            last_remove_offset = tmp_offset
            tmp_offset += 1
        elif dl.kind == DiffLineKind.CONTEXT:
            tmp_offset += 1

    first_remove_seen = False
    cur_offset = 0
    for dl in hunk.lines:
        if dl.kind == DiffLineKind.REMOVE:
            first_remove_seen = True
            cur_offset += 1
        elif dl.kind == DiffLineKind.CONTEXT:
            if not first_remove_seen:
                above_ctx.append(dl.text)
            elif cur_offset > last_remove_offset:
                below_ctx.append(dl.text)
            else:
                inner_ctx.append((cur_offset, dl.text))
            cur_offset += 1

    score = 0
    # Score above-context lines (match upward from candidate_start - 1)
    for i, ctx in enumerate(reversed(above_ctx)):
        file_idx = candidate_start - 1 - i
        if 0 <= file_idx < len(file_lines) and _normal(file_lines[file_idx]) == _normal(ctx):
            score += 1

    # Score below-context lines (match downward from candidate_end)
    for i, ctx in enumerate(below_ctx):
        file_idx = candidate_end + i
        if 0 <= file_idx < len(file_lines) and _normal(file_lines[file_idx]) == _normal(ctx):
            score += 1

    # Score inner-context lines (interleaved within candidate region)
    for offset, ctx in inner_ctx:
        file_idx = candidate_start + offset
        if 0 <= file_idx < len(file_lines) and _normal(file_lines[file_idx]) == _normal(ctx):
            score += 1

    return score


def _render_hunk_replacement(hunk: DiffHunk, file_lines: list[str], match_start: int) -> list[str]:
    """Reconstruct replacement lines preserving existing context indentation."""
    rendered: list[str] = []
    old_offset = 0
    for line in hunk.lines:
        if line.kind == DiffLineKind.REMOVE:
            old_offset += 1
        elif line.kind == DiffLineKind.CONTEXT:
            rendered.append(file_lines[match_start + old_offset])
            old_offset += 1
        else:
            rendered.append(line.text + "\n")
    return rendered


def apply_diff_operation(operation: DiffOperation, current: str, exists: bool = True) -> DiffApplyResult:
    """Apply operation using Hard Anchors + Soft Context Scoring."""
    if operation.is_creation:
        if any(line.kind != DiffLineKind.ADD for hunk in operation.hunks for line in hunk.lines):
            raise DiffProtocolError(f"Creation diff for '{operation.path}' must contain only + lines.")
        new_content = "".join(line.text + "\n" for h in operation.hunks for line in h.lines)
        return DiffApplyResult(
            target_path=operation.path,
            original_content=current,
            patched_content=new_content,
            hunks_applied=len(operation.hunks),
            is_created=True,
        )

    working = current
    for num, hunk in enumerate(operation.hunks, start=1):
        remove_lines = hunk.remove_lines
        file_lines = working.splitlines(keepends=True)

        if not remove_lines:
            ctx_text = hunk.context_lines
            if ctx_text:
                ctx_needle = [_normal(t) for t in ctx_text]
                ctx_matches = [
                    start
                    for start in range(len(file_lines) - len(ctx_needle) + 1)
                    if [_normal(file_lines[start + i]) for i in range(len(ctx_needle))] == ctx_needle
                ]
                if not ctx_matches:
                    finding = PatchDriftFinding(
                        hunk_index=num,
                        target_path=operation.path,
                        candidate_count=0,
                        max_score=0,
                        tied_candidates=0,
                        message=f"Hunk {num} context lines not found in '{operation.path}'.",
                    )
                    raise DiffProtocolError(finding.message, finding)
                if len(ctx_matches) > 1:
                    finding = PatchDriftFinding(
                        hunk_index=num,
                        target_path=operation.path,
                        candidate_count=len(ctx_matches),
                        max_score=0,
                        tied_candidates=len(ctx_matches),
                        message=f"Hunk {num} context lines are ambiguous ({len(ctx_matches)} matches).",
                    )
                    raise DiffProtocolError(finding.message, finding)

                ctx_start = ctx_matches[0]
                pre_ctx_count = 0
                for dl in hunk.lines:
                    if dl.kind == DiffLineKind.CONTEXT:
                        pre_ctx_count += 1
                    elif dl.kind == DiffLineKind.ADD:
                        break
                ins_point = ctx_start + pre_ctx_count
                new_lines = [t + "\n" for t in hunk.add_lines]
                working = "".join(file_lines[:ins_point] + new_lines + file_lines[ins_point:])
            else:
                new_lines = [dl.text + "\n" for dl in hunk.lines if dl.kind == DiffLineKind.ADD]
                working = working + "".join(new_lines)
            continue

        # Phase 1: Hard anchors search
        candidates = find_hard_anchor_matches(file_lines, remove_lines)
        if not candidates:
            finding = PatchDriftFinding(
                hunk_index=num,
                target_path=operation.path,
                candidate_count=0,
                max_score=0,
                tied_candidates=0,
                message=f"Hunk {num} for '{operation.path}': deleted lines (-) were not found verbatim in file.",
            )
            raise DiffProtocolError(finding.message, finding)

        if len(candidates) == 1:
            winner = candidates[0]
        else:
            # Phase 1.5: Soft context scoring
            region_len = len(remove_lines)
            scores = [score_soft_context(file_lines, c, c + region_len, hunk) for c in candidates]
            max_score = max(scores)
            winners = [c for c, s in zip(candidates, scores, strict=True) if s == max_score]

            if len(winners) != 1:
                finding = PatchDriftFinding(
                    hunk_index=num,
                    target_path=operation.path,
                    candidate_count=len(candidates),
                    max_score=max_score,
                    tied_candidates=len(winners),
                    message=(
                        f"Hunk {num} for '{operation.path}' is ambiguous: {len(candidates)} regions matched (-) "
                        f"and {len(winners)} tied on context score ({max_score} pts)."
                    ),
                )
                raise DiffProtocolError(finding.message, finding)
            winner = winners[0]

        # Phase 2: Apply hunk replacement
        leading_ctx = 0
        for dl in hunk.lines:
            if dl.kind == DiffLineKind.CONTEXT:
                leading_ctx += 1
            elif dl.kind == DiffLineKind.REMOVE:
                break

        render_start = winner - leading_ctx
        total_old_span = sum(1 for dl in hunk.lines if dl.kind != DiffLineKind.ADD)
        replacement = _render_hunk_replacement(hunk, file_lines, render_start)
        working = "".join(file_lines[:render_start] + replacement + file_lines[render_start + total_old_span:])

    return DiffApplyResult(
        target_path=operation.path,
        original_content=current,
        patched_content=working,
        hunks_applied=len(operation.hunks),
    )


def apply_diff_patch(patch_text: str, current_content: str, exists: bool = True) -> DiffApplyResult:
    """Convenience helper: parse single patch string and apply to current content."""
    ops, errors = parse_diff_operations(patch_text)
    if errors:
        first_err = errors[0][2]
        raise first_err
    if not ops:
        raise DiffProtocolError("No valid diff operations found in patch text.")
    return apply_diff_operation(ops[0], current_content, exists=exists)
