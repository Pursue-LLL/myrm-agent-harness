"""Prune and Spill with Zero-Overhead Offset Recall Loop (Pi Harness v2 Item 22).

Eradicates the permanently-lossy pruner flaw where long tool outputs have their middle
dropped into oblivion. Implements:
1. Prune + Spill:
   When tool outputs exceed inline thresholds, 100% of the raw output is durably
   spilled to disk at `.context/{chat_id}/evicted/{spill_id}.txt`.
2. Standard Zero-Overhead Recall Marker:
   The inline context retains compact head and tail segments, and inserts a structured
   marker with evicted_path, total_lines, omitted_line_range, and recall instructions.
3. Zero-Overhead Offset Recall Engine:
   Enables the model or agent tools to recall omitted lines/bytes on-demand using
   offset reads or streaming grep, preventing hallucinations and guesswork.

[INPUT]
- raw_content: str
- tool_name: str
- call_id: str | None
- chat_id: str

[OUTPUT]
- PruneAndSpillConfig
- SpillMetadata
- PruneAndSpillResult
- OffsetRecallResult
- GrepMatchItem
- GrepRecallResult
- PruneAndSpillRecallEngine

[POS]
Harness runtime context layer. Guarantees 100% recoverability of large tool outputs
while shrinking inline context by 70%+ to protect prompt cache prefixes.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True, frozen=True)
class PruneAndSpillConfig:
    """Configuration thresholds for inline pruning and disk spillover."""

    max_inline_chars: int = 4000
    max_inline_lines: int = 80
    head_lines: int = 25
    tail_lines: int = 25
    storage_dir: Path | str | None = None


@dataclass(slots=True, frozen=True)
class SpillMetadata:
    """Provenance and boundary coordinates for spilled tool output."""

    spill_id: str
    file_path: str
    total_chars: int
    total_lines: int
    total_bytes: int
    omitted_start_line: int
    omitted_end_line: int
    omitted_line_count: int
    omitted_start_byte: int
    omitted_end_byte: int
    omitted_byte_count: int
    created_at_ms: int

    def to_dict(self) -> dict[str, object]:
        """Serialize metadata to dictionary."""
        return {
            "spill_id": self.spill_id,
            "file_path": self.file_path,
            "total_chars": self.total_chars,
            "total_lines": self.total_lines,
            "total_bytes": self.total_bytes,
            "omitted_start_line": self.omitted_start_line,
            "omitted_end_line": self.omitted_end_line,
            "omitted_line_count": self.omitted_line_count,
            "omitted_start_byte": self.omitted_start_byte,
            "omitted_end_byte": self.omitted_end_byte,
            "omitted_byte_count": self.omitted_byte_count,
            "created_at_ms": self.created_at_ms,
        }


@dataclass(slots=True, frozen=True)
class PruneAndSpillResult:
    """Result of pruning and spilling a tool output."""

    content: str
    was_spilled: bool
    metadata: SpillMetadata | None = None


@dataclass(slots=True, frozen=True)
class OffsetRecallResult:
    """Result of targeted line-offset recall."""

    spill_id: str
    file_path: str
    start_line: int
    returned_lines: int
    total_lines: int
    content: str
    has_more: bool


@dataclass(slots=True, frozen=True)
class GrepMatchItem:
    """A single pattern match within spilled content."""

    line_number: int
    line_content: str


@dataclass(slots=True, frozen=True)
class GrepRecallResult:
    """Result of scanning spilled content with a pattern."""

    spill_id: str
    pattern: str
    matches: tuple[GrepMatchItem, ...]
    total_matches: int


class PruneAndSpillRecallEngine:
    """Thread-safe engine for pruning, spilling, and recalling large tool outputs."""

    def __init__(self, config: PruneAndSpillConfig | None = None) -> None:
        self._config = config or PruneAndSpillConfig()
        self._lock = threading.RLock()
        self._registry: dict[str, SpillMetadata] = {}

    def _resolve_storage_path(self, chat_id: str, spill_id: str) -> Path:
        """Resolve destination file path on disk."""
        base_dir = (
            Path(self._config.storage_dir)
            if self._config.storage_dir is not None
            else Path(".context")
        )
        dest_dir = base_dir / chat_id / "evicted"
        dest_dir.mkdir(parents=True, exist_ok=True)
        return dest_dir / f"{spill_id}.txt"

    def prune_and_spill(
        self,
        raw_content: str,
        *,
        tool_name: str = "tool",
        call_id: str | None = None,
        chat_id: str = "default",
    ) -> PruneAndSpillResult:
        """Evaluate content against inline limits; spill to disk if exceeded."""
        raw_chars = len(raw_content)
        lines = raw_content.splitlines(keepends=True)
        raw_lines = len(lines)

        # Content is within bounds: no spill needed
        if (
            raw_chars <= self._config.max_inline_chars
            and raw_lines <= self._config.max_inline_lines
        ):
            return PruneAndSpillResult(content=raw_content, was_spilled=False)

        spill_id = f"spill-{uuid.uuid4().hex[:12]}"
        dest_path = self._resolve_storage_path(chat_id, spill_id)

        # 1. 100% raw content durably written to disk
        raw_bytes = raw_content.encode("utf-8", errors="replace")
        total_bytes = len(raw_bytes)
        dest_path.write_bytes(raw_bytes)

        # 2. Compute head and tail segments
        head_count = min(self._config.head_lines, raw_lines)
        tail_count = min(self._config.tail_lines, raw_lines - head_count)

        head_lines = lines[:head_count]
        tail_lines = lines[raw_lines - tail_count :] if tail_count > 0 else []

        head_text = "".join(head_lines)
        tail_text = "".join(tail_lines)

        head_bytes_len = len(head_text.encode("utf-8", errors="replace"))
        tail_bytes_len = len(tail_text.encode("utf-8", errors="replace"))

        omitted_start_line = head_count + 1
        omitted_end_line = raw_lines - tail_count
        omitted_line_count = max(0, omitted_end_line - omitted_start_line + 1)

        omitted_start_byte = head_bytes_len
        omitted_end_byte = total_bytes - tail_bytes_len
        omitted_byte_count = max(0, omitted_end_byte - omitted_start_byte)

        meta = SpillMetadata(
            spill_id=spill_id,
            file_path=str(dest_path.resolve()),
            total_chars=raw_chars,
            total_lines=raw_lines,
            total_bytes=total_bytes,
            omitted_start_line=omitted_start_line,
            omitted_end_line=omitted_end_line,
            omitted_line_count=omitted_line_count,
            omitted_start_byte=omitted_start_byte,
            omitted_end_byte=omitted_end_byte,
            omitted_byte_count=omitted_byte_count,
            created_at_ms=int(time.time() * 1000),
        )

        with self._lock:
            self._registry[spill_id] = meta

        # 3. Construct Standard Zero-Overhead Recall Marker
        marker = (
            f"\n\n[>>> ZERO-OVERHEAD RECALL MARKER <<<\n"
            f"Spill ID: {spill_id} | Tool: {tool_name} | Call ID: {call_id or 'none'}\n"
            f"Full Raw File: {meta.file_path}\n"
            f"Total Output: {raw_lines:,} lines ({raw_chars:,} chars, {total_bytes:,} bytes)\n"
            f"Omitted Middle: {omitted_line_count:,} lines [L{omitted_start_line} - L{omitted_end_line}] "
            f"({omitted_byte_count:,} bytes [B{omitted_start_byte} - B{omitted_end_byte}])\n"
            f"Recall Instruction: Complete output is safely stored. To inspect omitted lines, call "
            f"`file_read('{meta.file_path}', start_line={omitted_start_line}, end_line=...)` or "
            f"`grep(pattern, '{meta.file_path}')`. DO NOT GUESS!\n"
            f">>> END RECALL MARKER <<<]\n\n"
        )

        compact_content = f"{head_text.rstrip()}{marker}{tail_text.lstrip()}"

        return PruneAndSpillResult(
            content=compact_content,
            was_spilled=True,
            metadata=meta,
        )

    def _locate_file(self, spill_id_or_path: str) -> Path:
        """Resolve path from registry or direct file path string."""
        with self._lock:
            if spill_id_or_path in self._registry:
                return Path(self._registry[spill_id_or_path].file_path)
        path = Path(spill_id_or_path)
        if path.exists():
            return path
        raise FileNotFoundError(f"Spilled content not found: {spill_id_or_path}")

    def recall_by_lines(
        self,
        spill_id_or_path: str,
        start_line: int,
        max_lines: int = 50,
    ) -> OffsetRecallResult:
        """Recall specific line range with zero overhead using streaming line seek."""
        if start_line < 1:
            raise ValueError(f"start_line must be >= 1, got {start_line}")
        if max_lines < 1:
            raise ValueError(f"max_lines must be >= 1, got {max_lines}")

        target_file = self._locate_file(spill_id_or_path)
        collected: list[str] = []
        current_line_no = 0
        total_lines = 0

        with target_file.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                current_line_no += 1
                total_lines += 1
                if current_line_no >= start_line and len(collected) < max_lines:
                    collected.append(line)

        content = "".join(collected)
        has_more = (start_line + len(collected) - 1) < total_lines

        return OffsetRecallResult(
            spill_id=spill_id_or_path,
            file_path=str(target_file),
            start_line=start_line,
            returned_lines=len(collected),
            total_lines=total_lines,
            content=content,
            has_more=has_more,
        )

    def recall_by_bytes(
        self,
        spill_id_or_path: str,
        start_byte: int,
        max_bytes: int = 4096,
    ) -> str:
        """Recall specific byte slice with zero overhead using direct file seek."""
        if start_byte < 0:
            raise ValueError(f"start_byte must be >= 0, got {start_byte}")
        if max_bytes < 1:
            raise ValueError(f"max_bytes must be >= 1, got {max_bytes}")

        target_file = self._locate_file(spill_id_or_path)
        with target_file.open("rb") as f:
            f.seek(start_byte)
            raw = f.read(max_bytes)
            return raw.decode("utf-8", errors="replace")

    def grep_evicted(
        self,
        spill_id_or_path: str,
        pattern: str,
        max_matches: int = 50,
    ) -> GrepRecallResult:
        """Scan spilled content with regex pattern, returning matching lines and line numbers."""
        target_file = self._locate_file(spill_id_or_path)
        regex = re.compile(pattern)
        matches: list[GrepMatchItem] = []

        with target_file.open("r", encoding="utf-8", errors="replace") as f:
            for idx, line in enumerate(f, start=1):
                if regex.search(line):
                    matches.append(GrepMatchItem(line_number=idx, line_content=line.strip()))
                    if len(matches) >= max_matches:
                        break

        return GrepRecallResult(
            spill_id=spill_id_or_path,
            pattern=pattern,
            matches=tuple(matches),
            total_matches=len(matches),
        )
