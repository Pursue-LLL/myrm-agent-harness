"""Head truncation helpers for file_read_tool output.

Compiler-grade read output: caps a read on a complete-line boundary so the
model never receives a half-line syntax fragment, and returns a precomputed
``next_offset`` so it can continue without guessing the pagination position.

[INPUT]
- (none)

[OUTPUT]
- truncate_file_output: smart head-truncation with precomputed next_offset

[POS]
Truncation utilities shared by file_read handlers and vault batch reads.
"""

from __future__ import annotations

import re

from .file_read_outline import extract_truncated_outline

# Matches the ``{LINE_NUMBER_WIDTH}|`` gutter emitted by ResultFormatter,
# e.g. ``     12|def foo()``. Used to derive the next_offset continuation line.
_GUTTER_LINE_RE = re.compile(r"^\s*(\d+)\|")

# Compact marker appended to the truncated block (openclaw/hermes-style).
_TRUNCATION_MARKER = "\n\n... [truncated]"


def _head_truncate_on_line_boundary(lines: list[str], max_chars: int) -> list[str]:
    """Trim *lines* to the last complete line that fits within *max_chars*.

    When not even the first line fits, clamps that single line on a code-point
    boundary (Python ``str`` slicing never splits a code point) so the read
    never returns empty and the cursor can still advance.
    """
    kept: list[str] = []
    running = 0
    for line in lines:
        # +1 for the "\n" that rejoins this line to the previous one.
        addition = len(line) + (1 if kept else 0)
        if running + addition > max_chars:
            break
        kept.append(line)
        running += addition

    if not kept:
        kept.append(lines[0][:max_chars])

    return kept


def _last_gutter_line_number(lines: list[str]) -> int | None:
    """Extract the 1-indexed line number of the last retained gutter line.

    Returns ``None`` when the content has no gutter (e.g. a directory listing
    or a raw read without line numbers).
    """
    if not lines:
        return None
    match = _GUTTER_LINE_RE.match(lines[-1])
    return int(match.group(1)) if match else None


def truncate_file_output(
    output: str,
    max_chars: int = 10000,
    is_dir: bool = False,
    path_str: str = "file",
    max_lines: int | None = None,
) -> tuple[str, bool, dict[str, object]]:
    """Head-truncate file/ls output with a precomputed continuation offset.

    Truncation is always on a complete-line boundary (except a single over-long
    line, clamped on a code-point boundary). The returned ``metadata`` includes
    ``next_offset`` = the last shown line number + 1 when the output carries a
    line-number gutter, so the model can continue with ``path:next_offset-``.

    Args:
        output: Raw or gutter-rendered file content.
        max_chars: Maximum characters admitted into context.
        is_dir: Whether *output* is a directory listing.
        path_str: Display path used in the continuation hint.
        max_lines: Optional line-count cap (``None`` disables it; the char
            budget is the primary guard).

    Returns:
        ``(truncated_text, was_truncated, metadata)``. When the output already
        fits both caps, it is returned unchanged with ``was_truncated=False``.
    """
    if len(output) <= max_chars and (max_lines is None or output.count("\n") + 1 <= max_lines):
        return output, False, {}

    total_lines = output.count("\n") + 1
    total_mb = len(output.encode("utf-8", errors="ignore")) / (1024 * 1024)

    lines = output.split("\n")

    if is_dir:
        dir_lines = lines[: max_lines] if max_lines is not None else lines
        dir_text = "\n".join(dir_lines)
        if len(dir_text) > max_chars:
            dir_lines = _head_truncate_on_line_boundary(dir_lines, max_chars)
            dir_text = "\n".join(dir_lines)
        hint = "[truncated... Use a more specific path to view fewer items]"
        return (
            f"{dir_text}{_TRUNCATION_MARKER}\n{hint}",
            True,
            {"type": "dir", "path": path_str, "total_lines": total_lines},
        )

    # Line-count cap first (cheap, bounds the work for the char scan).
    line_capped = max_lines is not None and len(lines) > max_lines
    if line_capped:
        lines = lines[: max_lines]

    # Char budget, then, on a complete-line boundary.
    char_capped = len("\n".join(lines)) > max_chars
    if char_capped:
        lines = _head_truncate_on_line_boundary(lines, max_chars)

    head = "\n".join(lines)

    # With a line-number gutter (ResultFormatter), next_offset is the last shown
    # line + 1. Without one (raw text / vault reads), fall back to the number of
    # retained lines + 1 so the hint is always a line number, never a char count.
    last_line = _last_gutter_line_number(lines)
    next_offset = last_line + 1 if last_line is not None else len(lines) + 1

    hint_parts: list[str] = []
    if line_capped or char_capped:
        hint_parts.append(f"showing first {len(lines):,} of {total_lines:,} lines")
    hint_parts.append(f"Use {path_str}:{next_offset}- to continue")

    hint = (
        f"[SYSTEM WARNING: Output capped at {max_chars:,} chars "
        f"({total_mb:.2f}MB, {total_lines:,} lines). "
        f"{', '.join(hint_parts)}.]"
    )

    outline = extract_truncated_outline(
        output=output,
        path_str=path_str,
        next_offset=next_offset,
    )
    if outline:
        hint = f"{hint}\n{outline}"

    metadata: dict[str, object] = {
        "type": "file",
        "path": path_str,
        "total_lines": total_lines,
        "total_mb": round(total_mb, 2),
        "shown_chars": len(head),
        "truncated": True,
    }
    if next_offset is not None:
        metadata["next_offset"] = next_offset

    return f"{head}{_TRUNCATION_MARKER}\n{hint}", True, metadata
