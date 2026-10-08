"""[POS]: src/myrm_agent_harness/toolkits/memory/migration/parsers.py
[INPUT]: Multi-platform serialized memory payloads and external file paths.
[OUTPUT]: MultiPlatformParserMatrix facade and unified parser class exports.
"""

from __future__ import annotations

from pathlib import Path

from myrm_agent_harness.toolkits.memory.migration.chat_parsers import (
    ChatExportParser,
    ClaudeProjectParser,
)
from myrm_agent_harness.toolkits.memory.migration.graph_parsers import (
    MemOSParser,
)
from myrm_agent_harness.toolkits.memory.migration.models import (
    ExtractedMemoryUnit,
    MigrationSourceType,
)
from myrm_agent_harness.toolkits.memory.migration.note_parsers import (
    HermesParser,
    MarkdownTreeParser,
    OpenClawParser,
)
from myrm_agent_harness.toolkits.memory.migration.security_guard import (
    MigrationSecurityGuard,
)


class MultiPlatformParserMatrix:
    """Unified facade intelligently dispatching artifacts to appropriate platform parsers."""

    def __init__(self, security_guard: MigrationSecurityGuard | None = None) -> None:
        self._guard = security_guard or MigrationSecurityGuard()
        self._openclaw_parser = OpenClawParser()
        self._hermes_parser = HermesParser()
        self._chat_parser = ChatExportParser()
        self._claude_parser = ClaudeProjectParser()
        self._memos_parser = MemOSParser()
        self._md_parser = MarkdownTreeParser()

    def parse_payload(
        self,
        source_type: MigrationSourceType,
        raw_content: str,
        source_id: str = "raw_input",
    ) -> list[ExtractedMemoryUnit]:
        """Dispatch in-memory text payload to corresponding platform parser."""
        if source_type == MigrationSourceType.OPENCLAW:
            return self._openclaw_parser.parse(raw_content, source_id, self._guard)
        if source_type == MigrationSourceType.HERMES:
            return self._hermes_parser.parse(raw_content, source_id, self._guard)
        if source_type == MigrationSourceType.CHATGPT_EXPORT:
            return self._chat_parser.parse(raw_content, source_id, self._guard)
        if source_type == MigrationSourceType.CLAUDE_PROJECT:
            return self._claude_parser.parse(raw_content, source_id, self._guard)
        if source_type == MigrationSourceType.MEMOS:
            return self._memos_parser.parse(raw_content, source_id, self._guard)
        if source_type == MigrationSourceType.MARKDOWN_TREE:
            return self._md_parser.parse(raw_content, source_id, self._guard)

        # Fallback to OpenClaw auto JSON/MD parser
        return self._openclaw_parser.parse(raw_content, source_id, self._guard)

    def parse_file(
        self,
        source_type: MigrationSourceType,
        file_path: Path | str,
    ) -> list[ExtractedMemoryUnit]:
        """Validate safety bounds and parse external file."""
        path = Path(file_path)
        if not path.is_file():
            return []

        self._guard.validate_file(path)
        raw_text = path.read_text(encoding="utf-8", errors="ignore")
        return self.parse_payload(source_type, raw_text, source_id=path.name)


__all__ = [
    "ChatExportParser",
    "ClaudeProjectParser",
    "HermesParser",
    "MarkdownTreeParser",
    "MemOSParser",
    "MultiPlatformParserMatrix",
    "OpenClawParser",
]
