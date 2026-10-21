"""Tool output statistical and semantic feature extraction.

[INPUT]
- (none)

[OUTPUT]
- extract_tool_stats: function — extract key stats and core semantic findings from tool output

[POS]
Extracts deterministic runtime metadata (lines, chars, tokens, exit_code)
and semantic findings (error lines, symbol definitions, search hits) without secondary LLM calls.
"""

from __future__ import annotations

import re

_ERROR_LINE_PATTERN = re.compile(
    r"^(?:.*?(?:error|exception|fail(?:ed)?|assertionerror|traceback|syntaxerror|typeerror)).*$",
    re.IGNORECASE | re.MULTILINE,
)
_PYTHON_DEF_PATTERN = re.compile(r"^\s*(?:class\s+([A-Za-z0-9_]+)|def\s+([A-Za-z0-9_]+))", re.MULTILINE)


def extract_tool_stats(
    tool_name: str, tool_content: str, tool_args: dict[str, object] | None = None
) -> dict[str, object]:
    """Extract key stats and core semantic findings from tool output."""
    del tool_args

    stats: dict[str, object] = {}
    chars = len(tool_content)
    lines = tool_content.count("\n") + 1 if tool_content.strip() else 0
    stats["chars"] = chars
    stats["lines"] = lines
    stats["exit_code"] = 0
    stats["findings"] = ""
    stats["summary"] = ""
    stats["error"] = ""

    if tool_name == "bash_code_execute_tool":
        exit_match = re.search(r"\[exit_code:\s*(-?\d+)", tool_content)
        if exit_match:
            stats["exit_code"] = int(exit_match.group(1))

    # Extract high-priority error findings if present
    error_matches = _ERROR_LINE_PATTERN.findall(tool_content)
    if error_matches:
        clean_errors = [m.strip()[:140] for m in error_matches[:2]]
        stats["error"] = " | ".join(clean_errors)
        stats["findings"] = f"Errors: {stats['error']}"

    if tool_name == "file_read_tool" and not stats["findings"]:
        # Extract top defined symbols to retain code orientation
        symbols: list[str] = []
        for match in _PYTHON_DEF_PATTERN.finditer(tool_content):
            sym = match.group(1) or match.group(2)
            if sym and sym not in symbols:
                symbols.append(sym)
            if len(symbols) >= 3:
                break
        if symbols:
            stats["findings"] = f"Symbols: {', '.join(symbols)}"

    truncated_lines = re.search(r"\[LARGE OUTPUT TRUNCATED \((\d+) lines", tool_content)
    if truncated_lines:
        stats["lines"] = int(truncated_lines.group(1))

    truncated = re.search(r"\[LARGE OUTPUT TRUNCATED \((\d+) lines,\s*~?(\d+) tokens\)", tool_content)
    if truncated:
        stats["lines"] = int(truncated.group(1))
        stats["tokens"] = int(truncated.group(2))

    if not stats["findings"]:
        stats["findings"] = f"{stats['lines']} lines, {chars} chars"

    stats["summary"] = stats["findings"]
    return stats
