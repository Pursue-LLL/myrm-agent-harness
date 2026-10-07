# [POS] src/myrm_agent_harness/toolkits/memory/external_bridge/conflict_detector.py
# [INPUT] models.py (MemoryConflictReport), pathlib.Path, re
# [OUTPUT] MemoryPluginConflictDetector

"""Detector for conflicting third-party memory extensions and incompatible instructions.

Scans workspace or target instructions to warn if existing legacy memory tools
or duplicated memory instructions might cause hallucination or competing recall loops.
"""

from __future__ import annotations

import re
from pathlib import Path

from myrm_agent_harness.toolkits.memory.external_bridge.models import MemoryConflictReport

KNOWN_CONFLICT_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"(?i)\bmem0\b", "Detected third-party Mem0 memory plugin reference"),
    (r"(?i)\bmss\b.*memory", "Detected third-party MSS memory plugin reference"),
    (r"(?i)\bzep\b.*memory", "Detected third-party Zep memory plugin reference"),
    (r"(?i)\bchatgpt-memory\b", "Detected third-party ChatGPT memory directive"),
    (r"(?i)save_memory_to_sqlite", "Detected legacy direct sqlite memory tool call"),
)


class MemoryPluginConflictDetector:
    """Detects competing memory tools or conflicting prompt rules in targets."""

    @classmethod
    def inspect_content(cls, content: str) -> MemoryConflictReport:
        """Inspect raw instruction content for conflicting memory directives."""
        conflicting_tools: list[str] = []
        conflicting_rules: list[str] = []
        advice: list[str] = []

        for pattern, desc in KNOWN_CONFLICT_PATTERNS:
            if re.search(pattern, content):
                conflicting_tools.append(pattern)
                conflicting_rules.append(desc)
                advice.append(f"Consider disabling or archiving: {desc}")

        has_conflict = len(conflicting_tools) > 0
        return MemoryConflictReport(
            has_conflict=has_conflict,
            conflicting_tools=conflicting_tools,
            conflicting_rules=conflicting_rules,
            advice=advice,
        )

    @classmethod
    def inspect_file(cls, file_path: Path) -> MemoryConflictReport:
        """Inspect existing configuration or instruction file on disk."""
        if not file_path.exists() or not file_path.is_file():
            return MemoryConflictReport(has_conflict=False)

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            return cls.inspect_content(content)
        except OSError:
            return MemoryConflictReport(has_conflict=False)
