"""Markdown structure-aware chunker preserving heading paths and code block fence integrity.

[INPUT]
- DocumentChunk, EphemeralFts5Config: Contract definitions.

[OUTPUT]
- MarkdownCodeBlockChunker: Deterministic chunker splitting markdown without severing code blocks.

[POS]
Document ingestion and structural segmentation layer for ephemeral session FTS5 vault.
"""

from __future__ import annotations

import hashlib
import re
from typing import Sequence

from .ephemeral_fts5_types import DocumentChunk, EphemeralFts5Config


class MarkdownCodeBlockChunker:
    """Splits markdown documents into bounded chunks while preserving headings and code fences."""

    def __init__(self, config: EphemeralFts5Config | None = None) -> None:
        self._config = config or EphemeralFts5Config()
        self._heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$")

    def chunk_document(
        self,
        document_id: str,
        content: str,
        session_id: str,
    ) -> Sequence[DocumentChunk]:
        """Parses markdown lines, tracks active heading stack, and yields intact code-safe chunks."""
        lines = content.splitlines(keepends=True)
        chunks: list[DocumentChunk] = []

        current_heading_stack: list[str] = []
        current_chunk_lines: list[str] = []
        in_code_fence = False
        chunk_idx = 0

        for line in lines:
            stripped = line.strip()
            # 1. Track code fence boundaries
            if stripped.startswith("```"):
                in_code_fence = not in_code_fence

            # 2. Heading detection (only outside code fences)
            if not in_code_fence:
                m = self._heading_pattern.match(stripped)
                if m:
                    # Flush current buffer if non-empty
                    if current_chunk_lines:
                        chunk = self._create_chunk(
                            document_id=document_id,
                            session_id=session_id,
                            chunk_index=chunk_idx,
                            lines=current_chunk_lines,
                            heading_stack=current_heading_stack,
                        )
                        if chunk:
                            chunks.append(chunk)
                            chunk_idx += 1
                        current_chunk_lines = []

                    level = len(m.group(1))
                    title = m.group(2).strip()
                    # Adjust heading stack according to level
                    current_heading_stack = current_heading_stack[: level - 1]
                    current_heading_stack.append(title)
                    current_chunk_lines.append(line)
                    continue

            # 3. Check character budget for current chunk
            current_chunk_lines.append(line)
            current_len = sum(len(ln) for ln in current_chunk_lines)

            # Only cut at paragraph breaks when outside code fences and exceeding max chars
            if (
                not in_code_fence
                and current_len >= self._config.max_chunk_chars
                and stripped == ""
            ):
                chunk = self._create_chunk(
                    document_id=document_id,
                    session_id=session_id,
                    chunk_index=chunk_idx,
                    lines=current_chunk_lines,
                    heading_stack=current_heading_stack,
                )
                if chunk:
                    chunks.append(chunk)
                    chunk_idx += 1
                current_chunk_lines = []

        # Flush trailing lines
        if current_chunk_lines:
            chunk = self._create_chunk(
                document_id=document_id,
                session_id=session_id,
                chunk_index=chunk_idx,
                lines=current_chunk_lines,
                heading_stack=current_heading_stack,
            )
            if chunk:
                chunks.append(chunk)

        return tuple(chunks)

    def _create_chunk(
        self,
        document_id: str,
        session_id: str,
        chunk_index: int,
        lines: Sequence[str],
        heading_stack: Sequence[str],
    ) -> DocumentChunk | None:
        text = "".join(lines).strip()
        if not text:
            return None

        has_code = "```" in text
        heading_path = " > ".join(heading_stack) if heading_stack else "root"
        chunk_id = f"{document_id}#chunk_{chunk_index:04d}"
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        char_count = len(text)
        token_est = max(1, (char_count + 3) // 4)

        return DocumentChunk(
            chunk_id=chunk_id,
            document_id=document_id,
            session_id=session_id,
            heading_path=heading_path,
            content=text,
            has_code_block=has_code,
            char_count=char_count,
            token_estimate=token_est,
            content_hash=content_hash,
        )
