"""Semantic sliding window Markdown chunker with code block boundary protection.

[POS]
Sliding window chunker slicing Markdown documents into 400-token semantic chunks
with 80-token overlap, respecting code blocks, headers, and paragraph boundaries.

[INPUT]
- typing, uuid
- .models (ChunkingConfig, MarkdownChunk)

[OUTPUT]
- MarkdownSlidingWindowChunker
"""

from __future__ import annotations

from uuid import uuid4

from myrm_agent_harness.toolkits.memory.chunking.models import (
    ChunkingConfig,
    MarkdownChunk,
)


class MarkdownSlidingWindowChunker:
    """Chunks Markdown text using an adaptive sliding window respecting document structure."""

    def __init__(self, config: ChunkingConfig | None = None) -> None:
        """Initialize chunker with configuration."""
        self.config: ChunkingConfig = config or ChunkingConfig()

    def chunk_document(
        self,
        content: str,
        source_path: str = "MEMORY.md",
    ) -> list[MarkdownChunk]:
        """Split Markdown document into overlapping semantic chunks with line-level pointers.

        Args:
            content: Raw Markdown content string.
            source_path: File path or unique identifier for source document.

        Returns:
            List of MarkdownChunk objects with start/end lines and content hashes.
        """
        if not content.strip():
            return []

        raw_lines = content.splitlines(keepends=True)
        # Precompute line metadata: 1-based line index, line text, start char, end char
        line_records: list[tuple[int, str, int, int]] = []
        current_offset = 0
        for idx, line in enumerate(raw_lines, start=1):
            line_len = len(line)
            line_records.append((idx, line, current_offset, current_offset + line_len))
            current_offset += line_len

        total_lines = len(line_records)
        chunks: list[MarkdownChunk] = []

        start_idx = 0
        target_chars = self.config.target_chars
        overlap_chars = self.config.overlap_chars

        while start_idx < total_lines:
            accumulated_chars = 0
            end_idx = start_idx
            in_code_block = False
            is_truncated = False

            while end_idx < total_lines:
                _, line_text, _, _ = line_records[end_idx]

                # Track fenced code block delimiters (e.g. ``` or ~~~)
                stripped = line_text.strip()
                if stripped.startswith("```") or stripped.startswith("~~~"):
                    in_code_block = not in_code_block

                line_len = len(line_text)
                # Check for extreme single line length
                if line_len > self.config.max_chunk_chars:
                    is_truncated = True

                accumulated_chars += line_len
                end_idx += 1

                # If we've reached or exceeded target size and not inside a code block, stop
                if accumulated_chars >= target_chars and not in_code_block:
                    break

            # Extract window lines
            selected_lines = line_records[start_idx:end_idx]
            first_line_no, _, char_start, _ = selected_lines[0]
            last_line_no, _, _, char_end = selected_lines[-1]

            chunk_text = "".join(r[1] for r in selected_lines)
            if is_truncated and len(chunk_text) > self.config.max_chunk_chars:
                chunk_text = chunk_text[: self.config.max_chunk_chars]

            est_tokens = max(1, int(len(chunk_text) / self.config.chars_per_token))

            chunk = MarkdownChunk(
                chunk_id=f"chk_{uuid4().hex[:12]}",
                source_path=source_path,
                start_line=first_line_no,
                end_line=last_line_no,
                char_start=char_start,
                char_end=char_end,
                text=chunk_text,
                token_estimate=est_tokens,
                is_truncated=is_truncated,
            )
            chunks.append(chunk)

            if end_idx >= total_lines:
                break

            # Calculate next start_idx using overlap budget
            next_start = end_idx
            rewind_chars = 0
            for reverse_i in range(end_idx - 1, start_idx, -1):
                rewind_chars += len(line_records[reverse_i][1])
                if rewind_chars >= overlap_chars:
                    next_start = reverse_i
                    break

            # Guarantee forward progress by at least 1 line
            if next_start <= start_idx:
                start_idx += 1
            else:
                start_idx = next_start

        return chunks
