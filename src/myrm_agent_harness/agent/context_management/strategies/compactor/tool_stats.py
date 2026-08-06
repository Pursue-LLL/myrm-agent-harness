"""工具输出统计提取。

[INPUT]
- (none)

[OUTPUT]
- extract_tool_stats: function — extract_tool_stats

[POS]
Provides extract_tool_stats.
"""

from __future__ import annotations

import re


def extract_tool_stats(
    tool_name: str, tool_content: str, tool_args: dict[str, object] | None = None
) -> dict[str, object]:
    """从工具输出中提取关键统计信息。"""
    del tool_args

    stats: dict[str, object] = {}
    chars = len(tool_content)
    lines = tool_content.count("\n") + 1 if tool_content.strip() else 0
    stats["chars"] = chars
    stats["lines"] = lines

    if tool_name == "bash_code_execute_tool":
        exit_match = re.search(r"\[exit_code:\s*(-?\d+)", tool_content)
        stats["exit_code"] = int(exit_match.group(1)) if exit_match else 0

    if tool_name == "file_read_tool":
        truncated_lines = re.search(r"\[LARGE OUTPUT TRUNCATED \((\d+) lines", tool_content)
        if truncated_lines:
            stats["lines"] = int(truncated_lines.group(1))

    truncated = re.search(r"\[LARGE OUTPUT TRUNCATED \((\d+) lines,\s*~?(\d+) tokens\)", tool_content)
    if truncated:
        stats["lines"] = int(truncated.group(1))
        stats["tokens"] = int(truncated.group(2))

    return stats
