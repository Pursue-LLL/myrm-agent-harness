"""Overlap processing module.

Handles chunk merging, overlap extraction, and overlap insertion.

## Features

### 1. Overlap Purpose
During text splitting, overlapping content is added between adjacent chunks to maintain context
continuity:

```
Original split (no overlap):
chunk1: "...end of paragraph A."
chunk2: "Start of paragraph B..."
 Context break

With overlap:
chunk1: "...end of paragraph A."
chunk2: "end of paragraph A. Start of paragraph B..." # includes tail of previous chunk
 Context continuity
```

### 2. Small Chunk Merging
Prevents overly small chunks (< 80% of chunk_size):

```
Original split:
chunk1: 100 tokens (too small)
chunk2: 150 tokens (too small)
chunk3: 500 tokens (normal)

After merging:
chunk1: 250 tokens (100+150 merged)
chunk2: 500 tokens (kept)
```

### 3. Special Block Integrity Protection
When extracting overlap, ensures special blocks are not split:

```
Chunk tail:
...normal text
```python
def func():
```

When extracting overlap:
 Wrong: includes incomplete code block start
 Correct: excludes code block, takes only normal text
```

## Usage

```python
processor = OverlapProcessor(
    chunk_size=500,
    chunk_overlap=50,
    max_with_special=1000,
    length_function=token_counter,
    detector=detector
)

# Merge small chunks
chunks = ["small_chunk1", "small_chunk2", "normal_chunk"]
merged = processor.merge_small_chunks(chunks)

# Add overlap
chunks = ["chunk1", "chunk2", "chunk3"]
overlapped = processor.add_overlap_to_chunks(chunks)
# chunk2 will include the last 50 tokens of chunk1
# chunk3 will include the last 50 tokens of chunk2
```

## Technical Details

- Overlap is extracted from the tail of the previous chunk
- Overlap does not consume the current chunk's content quota
- Chunk size after overlap is approximately: chunk_size + overlap_size
- Intelligently detects and protects code blocks, tables, and other special structures

[INPUT]
- (none)

[OUTPUT]
- OverlapProcessor: class — Overlap Processor
- func: import re

[POS]
Overlap processing module.
"""

import re
from collections.abc import Callable

from .special_block_detector import SpecialBlockDetector


class OverlapProcessor:
    """Overlap processor for chunk merging and overlap management."""

    def __init__(
        self,
        chunk_size: int,
        chunk_overlap: int,
        max_with_special: int,
        length_function: Callable[[str], int],
        detector: SpecialBlockDetector,
    ):
        """Initialize the overlap processor.

        Args:
            chunk_size: Target chunk size
            chunk_overlap: Overlap size
            max_with_special: Maximum allowed size for special blocks
            length_function: Token counting function
            detector: Special block detector
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.max_with_special = max_with_special
        self._length_function = length_function
        self._detector = detector

        self._heading_marker_pattern = re.compile(r"\n#{1,6}\s*$")

    def merge_small_chunks(self, chunks: list[str]) -> list[str]:
        """Merge undersized chunks.

        Strategy:
        1. If a chunk is less than 80% of chunk_size, attempt to merge with adjacent chunk
        2. Merge if combined size does not exceed max_with_special - overlap
        3. Iterate until no more merges are possible

        Notes:
        - The chunks list contains both normal text and already-processed special blocks
        - Small special blocks (<80% chunk_size) can be merged with normal text
        - Merge limit is max_with_special - overlap (reserving space for later overlap)

        Args:
            chunks: List of chunks

        Returns:
            Merged chunk list
        """
        if not chunks:
            return chunks

        min_chunk_size = int(self.chunk_size * 0.8)
        max_merged_size = self.max_with_special - self.chunk_overlap

        merged = chunks
        while True:
            new_merged = []
            i = 0
            has_merged = False

            while i < len(merged):
                current_chunk = merged[i]
                current_size = self._length_function(current_chunk)

                # If current chunk is large enough, add directly
                if current_size >= min_chunk_size:
                    new_merged.append(current_chunk)
                    i += 1
                    continue

                # Current chunk is too small — try merging with next
                if i + 1 < len(merged):
                    next_chunk = merged[i + 1]
                    combined = self._smart_combine_chunks(current_chunk, next_chunk)
                    combined_size = self._length_function(combined)

                    if combined_size <= max_merged_size:
                        new_merged.append(combined)
                        i += 2
                        has_merged = True
                        continue

                # If this is the last chunk and too small, try merging with previous
                if i == len(merged) - 1 and current_size < min_chunk_size and new_merged:
                    last = new_merged[-1]
                    last_size = self._length_function(last)

                    # Only merge if previous chunk is also under 80%
                    if last_size < min_chunk_size:
                        combined = self._smart_combine_chunks(last, current_chunk)
                        combined_size = self._length_function(combined)

                        if combined_size <= max_merged_size:
                            new_merged.pop()
                            new_merged.append(combined)
                            has_merged = True
                            i += 1
                            continue

                # Cannot merge — keep as-is
                new_merged.append(current_chunk)
                i += 1

            merged = new_merged

            # Exit if no merges occurred this round
            if not has_merged:
                break

        return merged

    def add_overlap_to_chunks(self, chunks: list[str]) -> list[str]:
        """Add overlap to chunks (unified processing).

        Overlap is duplicate content (from the previous chunk) and does not consume the
        current chunk's content quota. After adding overlap, chunk size is approximately
        chunk_size + overlap_size, which is expected.

        Args:
            chunks: List of chunks

        Returns:
            Chunk list with overlap added
        """
        if len(chunks) <= 1 or self.chunk_overlap <= 0:
            return chunks

        overlapped = []
        for i, chunk in enumerate(chunks):
            if i == 0:
                overlapped.append(chunk)
            else:
                # Extract overlap from previous chunk's tail
                prev_chunk = chunks[i - 1]
                overlap_text = self.extract_overlap(prev_chunk)

                if overlap_text:
                    # Check if current chunk already contains the overlap (avoid duplication)
                    chunk_start = chunk[: len(overlap_text) + 50]
                    if overlap_text.strip() not in chunk_start:
                        chunk_with_overlap = self._smart_combine_chunks(overlap_text, chunk)
                        overlapped.append(chunk_with_overlap)
                    else:
                        overlapped.append(chunk)
                else:
                    overlapped.append(chunk)

        return overlapped

    def extract_overlap(self, chunk: str, max_tokens: int | None = None) -> str:
        """Extract overlap content from chunk tail (preserving special block integrity).

        Strategy (simplified):
        1. Accumulate lines from the end of the chunk backwards
        2. Check if the overlap start splits a special block
        3. If split:
           - Attempt to extend forward to include the complete block (up to overlap*1.2)
           - If extended size exceeds limit, shrink to exclude the incomplete part

        Args:
            chunk: Chunk content
            max_tokens: Maximum token count

        Returns:
            Overlap text
        """
        if not chunk:
            return ""

        target_overlap = max_tokens if max_tokens is not None else self.chunk_overlap
        if target_overlap <= 0:
            return ""

        lines = chunk.split("\n")

        # Step 1: Base accumulation (from end backwards)
        overlap_lines = []
        current_tokens = 0

        for line in reversed(lines):
            line_tokens = self._length_function(line + "\n")
            if current_tokens + line_tokens > target_overlap:
                break
            overlap_lines.insert(0, line)
            current_tokens += line_tokens

        if not overlap_lines:
            return ""

        overlap_text = "\n".join(overlap_lines)
        overlap_start_idx = len(lines) - len(overlap_lines)

        # Step 2: Check special block integrity at overlap start
        adjusted_overlap = self._ensure_special_blocks_complete_at_start(
            lines, overlap_start_idx, overlap_text, target_overlap
        )

        return adjusted_overlap

    def _smart_combine_chunks(self, chunk1: str, chunk2: str) -> str:
        """Intelligently join two chunks.

        If chunk1 ends with a heading marker and chunk2 is heading text, join with space.
        Otherwise join with double newline.

        Args:
            chunk1: First chunk
            chunk2: Second chunk

        Returns:
            Combined text
        """
        chunk1_stripped = chunk1.rstrip()
        chunk2_stripped = chunk2.lstrip()

        if self._heading_marker_pattern.search(chunk1_stripped) and not chunk2_stripped.startswith("#"):
            # Separated heading marker and heading text — join with space
            return chunk1 + " " + chunk2
        else:
            return chunk1 + "\n\n" + chunk2

    def _ensure_special_blocks_complete_at_start(
        self, all_lines: list[str], overlap_start_idx: int, overlap_text: str, target_overlap: int
    ) -> str:
        """Ensure special blocks in overlap are complete.

        Checks whether the overlap start and end split a special block:
        1. Code block: checks if ``` count is balanced
        2. Table: checks for separator row missing header, or trailing table data without full table
        3. List: not handled (too complex)

        Args:
            all_lines: All lines in the chunk
            overlap_start_idx: Line index where overlap begins
            overlap_text: Initial overlap text
            target_overlap: Target overlap size

        Returns:
            Adjusted overlap
        """
        overlap_lines = overlap_text.split("\n")

        # 1. Check code blocks
        fence_count = overlap_text.count("```")
        if fence_count % 2 == 1:
            # Odd number of ``` — code block was split
            adjusted = self._adjust_code_block_overlap(all_lines, overlap_start_idx, overlap_lines, target_overlap)
            if adjusted is not None:
                return adjusted

        # 2. Check table — start check
        if overlap_lines and self._detector.is_table_separator_line(overlap_lines[0]):
            adjusted = self._adjust_table_overlap_at_start(all_lines, overlap_start_idx, overlap_lines, target_overlap)
            if adjusted is not None:
                return adjusted

        # 3. Check if overlap starts with a table data row
        if overlap_lines and "|" in overlap_lines[0]:
            adjusted = self._adjust_table_data_overlap(all_lines, overlap_start_idx, overlap_lines)
            if adjusted is not None:
                return adjusted

        # 4. Check if overlap ends with incomplete table rows
        adjusted = self._adjust_table_overlap_at_end(all_lines, overlap_start_idx, overlap_lines)
        if adjusted is not None:
            return adjusted

        return overlap_text

    def _adjust_code_block_overlap(
        self, all_lines: list[str], overlap_start_idx: int, overlap_lines: list[str], target_overlap: int
    ) -> str | None:
        """Adjust code block overlap (ensure ``` are paired)."""
        # Search backwards for the matching ```
        extended_lines = list(overlap_lines)
        for i in range(overlap_start_idx - 1, -1, -1):
            extended_lines.insert(0, all_lines[i])
            if "```" in all_lines[i]:
                # Found matching ```
                extended_text = "\n".join(extended_lines)
                extended_tokens = self._length_function(extended_text)

                if extended_tokens <= target_overlap * 1.2:
                    return extended_text
                else:
                    # Cannot include — shrink overlap to exclude code block
                    for j, line in enumerate(overlap_lines):
                        if "```" in line:
                            if j + 1 < len(overlap_lines):
                                return "\n".join(overlap_lines[j + 1 :])
                            else:
                                return ""
                    break
        return None

    def _adjust_table_overlap_at_start(
        self, all_lines: list[str], overlap_start_idx: int, overlap_lines: list[str], target_overlap: int
    ) -> str | None:
        """Adjust table overlap (starts with separator row)."""
        # Overlap starts with a table separator row — missing header
        if overlap_start_idx > 0:
            header_line = all_lines[overlap_start_idx - 1]
            if "|" in header_line:
                # Found header — attempt to include it
                extended_text = header_line + "\n" + "\n".join(overlap_lines)
                extended_tokens = self._length_function(extended_text)

                if extended_tokens <= target_overlap * 1.2:
                    return extended_text

        # Cannot include complete table — exclude separator and subsequent table content
        non_table_idx = 0
        for i, line in enumerate(overlap_lines):
            if "|" not in line:
                non_table_idx = i
                break
        else:
            return ""

        if non_table_idx > 0:
            return "\n".join(overlap_lines[non_table_idx:])
        return ""

    def _adjust_table_data_overlap(
        self, all_lines: list[str], overlap_start_idx: int, overlap_lines: list[str]
    ) -> str | None:
        """Adjust table data row overlap."""
        # Check if there is a separator row before the overlap start
        has_separator_before = False
        for i in range(overlap_start_idx - 1, max(0, overlap_start_idx - 5), -1):
            if self._detector.is_table_separator_line(all_lines[i]):
                has_separator_before = True
                break
            if "|" not in all_lines[i]:
                break

        if has_separator_before:
            # Overlap starts with an incomplete table data row — exclude
            non_table_idx = 0
            for i, line in enumerate(overlap_lines):
                if "|" not in line:
                    non_table_idx = i
                    break
            else:
                return ""

            if non_table_idx > 0:
                return "\n".join(overlap_lines[non_table_idx:])

        return None

    def _adjust_table_overlap_at_end(
        self, all_lines: list[str], overlap_start_idx: int, overlap_lines: list[str]
    ) -> str | None:
        """Adjust table overlap (trailing incomplete table)."""
        # Search backwards for consecutive | lines
        last_table_line_idx = -1
        for i in range(len(overlap_lines) - 1, -1, -1):
            if "|" in overlap_lines[i]:
                last_table_line_idx = i
            else:
                break

        if last_table_line_idx >= 0:
            # Overlap ends with table rows — check completeness
            table_lines_at_end = overlap_lines[last_table_line_idx:]

            # Check if these table lines contain a separator row
            has_separator = any(self._detector.is_table_separator_line(line) for line in table_lines_at_end)

            if not has_separator:
                # Search backwards for complete table structure
                found_complete_table = False
                if overlap_start_idx > 0:
                    for i in range(overlap_start_idx + last_table_line_idx - 1, max(-1, overlap_start_idx - 10), -1):
                        if i >= len(all_lines):
                            continue
                        if self._detector.is_table_separator_line(all_lines[i]):
                            if i > 0 and "|" in all_lines[i - 1]:
                                found_complete_table = True
                                break
                        elif "|" not in all_lines[i]:
                            break

                if not found_complete_table:
                    # Exclude trailing table rows
                    if last_table_line_idx > 0:
                        return "\n".join(overlap_lines[:last_table_line_idx])
                    else:
                        return ""

        return None
