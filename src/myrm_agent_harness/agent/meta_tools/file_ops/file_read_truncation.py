"""Head truncation helpers for file_read_tool output.

[INPUT]
- (none)

[OUTPUT]
- truncate_file_output: smart head-truncation with pagination hints

[POS]
Truncation utilities shared by file_read handlers and vault batch reads.
"""

from __future__ import annotations


def truncate_file_output(
    output: str, max_chars: int = 10000, is_dir: bool = False, path_str: str = "file"
) -> tuple[str, bool, dict[str, object]]:
    """Smart head-truncation for file/ls output with pagination hint."""
    if len(output) <= max_chars:
        return output, False, {}
    head = output[:max_chars]

    if is_dir:
        hint = "[truncated... Use a more specific path to view fewer items]"
        return f"{head}\n\n...{hint}", True, {"type": "dir", "path": path_str}

    total_lines = output.count("\n") + 1
    total_mb = len(output.encode("utf-8", errors="ignore")) / (1024 * 1024)

    hint = (
        f"[SYSTEM WARNING: File is extremely large ({total_mb:.2f}MB, {total_lines} lines). "
        f"Output has been TRUNCATED at {max_chars} chars. You are ONLY seeing the top portion. "
        f"Use start_line/end_line syntax (e.g. {path_str}:100-200) to read specific sections.]"
    )

    metadata: dict[str, object] = {
        "type": "file",
        "path": path_str,
        "total_lines": total_lines,
        "total_mb": round(total_mb, 2),
        "shown_chars": max_chars,
    }
    return f"{head}\n\n...{hint}", True, metadata
