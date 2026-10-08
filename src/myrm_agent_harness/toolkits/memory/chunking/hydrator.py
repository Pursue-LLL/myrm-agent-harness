"""Context hydration utility for expanding retrieved Markdown chunks.

[POS]
Utility hydrating retrieved Markdown chunks into full surrounding context
using start_line and end_line pointers against source document content.

[INPUT]
- pathlib.Path
- .models (MarkdownChunk)

[OUTPUT]
- ChunkSourceHydrator
"""

from __future__ import annotations

from pathlib import Path

from myrm_agent_harness.toolkits.memory.chunking.models import MarkdownChunk


class ChunkSourceHydrator:
    """Expands retrieved chunks into larger surrounding document context."""

    @staticmethod
    def hydrate_context(
        chunk: MarkdownChunk,
        full_document: str,
        window_lines: int = 3,
    ) -> str:
        """Hydrate surrounding context around chunk using line pointers.

        Args:
            chunk: Retrieved MarkdownChunk with start_line and end_line pointers.
            full_document: Complete raw text of source document.
            window_lines: Number of lines to expand before and after.

        Returns:
            Expanded text snippet containing leading context, target chunk, and trailing context.
        """
        if not full_document:
            return chunk.text

        lines = full_document.splitlines(keepends=True)
        total_lines = len(lines)
        if total_lines == 0:
            return chunk.text

        # start_line and end_line are 1-based indices
        ctx_start = max(1, chunk.start_line - window_lines)
        ctx_end = min(total_lines, chunk.end_line + window_lines)

        expanded_lines = lines[ctx_start - 1 : ctx_end]
        return "".join(expanded_lines)

    @classmethod
    def hydrate_from_file(
        cls,
        chunk: MarkdownChunk,
        base_dir: str | Path | None = None,
        window_lines: int = 3,
    ) -> str:
        """Hydrate chunk context directly from file system path if file exists."""
        target_path = Path(chunk.source_path)
        if base_dir and not target_path.is_absolute():
            target_path = Path(base_dir) / target_path

        if not target_path.exists() or not target_path.is_file():
            return chunk.text

        try:
            content = target_path.read_text(encoding="utf-8", errors="replace")
            return cls.hydrate_context(chunk, content, window_lines=window_lines)
        except Exception:
            return chunk.text
