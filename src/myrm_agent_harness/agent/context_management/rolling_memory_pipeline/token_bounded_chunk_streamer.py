"""Streamer slicing massive documents into token-bounded chunks with paragraph boundary preservation.

[INPUT]
- ChunkStreamConfig: Token limits and overlap parameters.
- TextChunk: Output chunk entity.

[OUTPUT]
- TokenBoundedChunkStreamer: Pure stream transformer producing cleanly segmented TextChunk series.

[POS]
Text chunking and streaming ingress layer for Uni-Agent MemAgent architecture.
"""

from __future__ import annotations

from typing import Sequence

from .rolling_memory_types import ChunkStreamConfig, TextChunk


class TokenBoundedChunkStreamer:
    """Slices large source text into token-bounded sequential chunks preserving natural paragraphs."""

    def __init__(self, config: ChunkStreamConfig | None = None) -> None:
        self._config = config or ChunkStreamConfig()

    def stream_chunks(self, text: str) -> Sequence[TextChunk]:
        """Splits full document into a sequence of bounded TextChunk objects."""
        if not text:
            return ()

        # Heuristic: 4 characters per token
        target_char_size = max(100, self._config.chunk_token_budget * 4)
        overlap_char_size = max(0, self._config.overlap_tokens * 4)

        text_len = len(text)
        if text_len <= target_char_size:
            est_tokens = max(1, (text_len + 3) // 4)
            return (
                TextChunk(
                    chunk_index=1,
                    total_chunks=1,
                    text_content=text,
                    token_estimate=est_tokens,
                    char_offset_start=0,
                    char_offset_end=text_len,
                ),
            )

        raw_slices: list[tuple[int, int, str]] = []
        start_pos = 0

        while start_pos < text_len:
            tentative_end = min(text_len, start_pos + target_char_size)

            if tentative_end < text_len:
                # Seek nearby natural paragraph or sentence boundary
                boundary_search_window = text[
                    max(start_pos, tentative_end - 500) : min(text_len, tentative_end + 300)
                ]
                # Look for paragraph break
                nl_idx = boundary_search_window.rfind("\n\n")
                if nl_idx == -1:
                    nl_idx = boundary_search_window.rfind("\n")

                if nl_idx != -1:
                    actual_cut = max(start_pos, tentative_end - 500) + nl_idx + 2
                    if actual_cut > start_pos + 100:
                        tentative_end = min(text_len, actual_cut)

            chunk_str = text[start_pos:tentative_end]
            raw_slices.append((start_pos, tentative_end, chunk_str))

            if tentative_end >= text_len:
                break

            # Advance with overlap
            next_start = max(start_pos + 1, tentative_end - overlap_char_size)
            start_pos = next_start

        total_count = len(raw_slices)
        chunks: list[TextChunk] = []

        for idx, (c_start, c_end, content) in enumerate(raw_slices, start=1):
            est_tokens = max(1, (len(content) + 3) // 4)
            chunks.append(
                TextChunk(
                    chunk_index=idx,
                    total_chunks=total_count,
                    text_content=content,
                    token_estimate=est_tokens,
                    char_offset_start=c_start,
                    char_offset_end=c_end,
                )
            )

        return tuple(chunks)
