"""High-throughput lightweight content sniffer for polymorphic tool outputs.

[INPUT]
- pipeline.processors.content_router_types::ToolResultFormatKind

[OUTPUT]
- ToolResultContentSniffer: 毫秒级内容类型嗅探器
"""

from __future__ import annotations

import json
import re

from .content_router_types import ToolResultFormatKind


class ToolResultContentSniffer:
    """Lightweight heuristic and regex sniffer for tool execution results (<0.5ms)."""

    _DIFF_HEADER_RE = re.compile(
        r"^(diff --git|--- a/|\+\+\+ b/|@@ -\d+,\d+ \+\d+,\d+ @@|@@@)",
        re.MULTILINE,
    )
    _GREP_LINE_RE = re.compile(r"^([^:\s\n]+):(\d+):(.*)$")
    _MD_TABLE_SEP_RE = re.compile(r"^\|(\s*:?-+:?\s*\|)+\s*$", re.MULTILINE)

    @classmethod
    def sniff(cls, text: str) -> ToolResultFormatKind:
        """Sniff raw content and classify into primary format kind."""
        if not text:
            return ToolResultFormatKind.PLAIN_TEXT

        stripped = text.strip()

        # 1. Probe JSON Array
        if stripped.startswith("[") and stripped.endswith("]"):
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, list) and len(parsed) > 0 and all(isinstance(x, dict) for x in parsed):
                    return ToolResultFormatKind.JSON_ARRAY
            except Exception:
                pass

        # 2. Probe Unified Diff
        diff_matches = cls._DIFF_HEADER_RE.findall(stripped)
        if len(diff_matches) >= 2 or ("diff --git" in stripped and "@@ -" in stripped):
            return ToolResultFormatKind.UNIFIED_DIFF

        lines = [line.strip() for line in stripped.splitlines() if line.strip()]
        if not lines:
            return ToolResultFormatKind.PLAIN_TEXT

        # 3. Probe Grep Matches (multiple lines matching filepath:linenumber:code)
        grep_count = sum(1 for line in lines if cls._GREP_LINE_RE.match(line))
        if len(lines) >= 3 and (grep_count / len(lines)) >= 0.7:
            return ToolResultFormatKind.GREP_MATCHES

        # 4. Probe Tabular (Markdown Table or CSV)
        if cls._MD_TABLE_SEP_RE.search(stripped):
            return ToolResultFormatKind.TABULAR
        if len(lines) >= 3 and "," in lines[0] and all(line.count(",") >= 2 for line in lines[:3]):
            return ToolResultFormatKind.TABULAR

        # 5. Probe Repeated Logs (consecutive identical lines)
        repeat_run = 0
        for i in range(len(lines) - 1):
            if lines[i] == lines[i + 1]:
                repeat_run += 1
                if repeat_run >= 2:
                    return ToolResultFormatKind.REPEATED_LOGS
            else:
                repeat_run = 0

        return ToolResultFormatKind.PLAIN_TEXT
