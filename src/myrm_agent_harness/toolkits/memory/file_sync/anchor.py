"""Memory anchor formatter for transparent source citations and line anchors.

[INPUT]
- myrm_agent_harness.toolkits.memory.file_sync.models::FileMemoryEntry (POS: structured memory chunk)

[OUTPUT]
- MemoryAnchorFormatter: contextual markdown formatter with line citations

[POS]
Formats memory entries with exact source file and line-range anchors for model prompt injection.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.file_sync.models import FileMemoryEntry


class MemoryAnchorFormatter:
    """Formats retrieved memory entries into clean markdown blocks with line anchors."""

    @staticmethod
    def format_entry(entry: FileMemoryEntry) -> str:
        """Format a single FileMemoryEntry into a citation block."""
        anchor_tag = entry.to_anchor()
        header = f"### {entry.title} {anchor_tag}" if entry.title else f"### {anchor_tag}"
        return f"{header}\n\n{entry.content.strip()}"

    @staticmethod
    def format_batch(entries: list[FileMemoryEntry]) -> str:
        """Format a list of entries into a consolidated memory context block."""
        if not entries:
            return ""
        blocks: list[str] = [
            "<workspace_memory_context>",
            "<!-- Preserves transparent local file provenance -->",
        ]
        for entry in entries:
            blocks.append(MemoryAnchorFormatter.format_entry(entry))
        blocks.append("</workspace_memory_context>")
        return "\n\n".join(blocks)

    @staticmethod
    def build_anchor(source_file: str, line_start: int, line_end: int | None = None) -> str:
        """Generate a standalone anchor citation string."""
        if line_end is None or line_start == line_end:
            return f"[source: {source_file}#L{line_start}]"
        return f"[source: {source_file}#L{line_start}-L{line_end}]"
