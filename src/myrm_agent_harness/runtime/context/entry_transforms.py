"""Entry transform plugins for post-compaction context pruning and deduplication.

Provides extensible transformations applied to retained context entries,
including execution log folding and duplicate warning suppression.
"""

from abc import ABC, abstractmethod

from .append_only_compaction_types import ContextEntryRole, ContextLogEntry


class BaseEntryTransform(ABC):
    """Abstract base class for entry post-processing transformers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this transform."""

    @abstractmethod
    def transform(self, entries: list[ContextLogEntry]) -> list[ContextLogEntry]:
        """Process and transform retained entries into a pruned/optimized list."""


class LongExecutionLogPrunerTransform(BaseEntryTransform):
    """Folds overly long execution or build logs into compact semantic stubs."""

    def __init__(self, max_lines: int = 15, head_lines: int = 5, tail_lines: int = 5) -> None:
        """Initialize log pruner thresholds."""
        self._max_lines = max_lines
        self._head_lines = head_lines
        self._tail_lines = tail_lines

    @property
    def name(self) -> str:
        """Transformer name."""
        return "LongExecutionLogPrunerTransform"

    def transform(self, entries: list[ContextLogEntry]) -> list[ContextLogEntry]:
        """Fold internal lines of long tool results into compact summary brackets."""
        pruned_entries: list[ContextLogEntry] = []

        for entry in entries:
            if entry.role != ContextEntryRole.TOOL_RESULT:
                pruned_entries.append(entry)
                continue

            lines = entry.content.splitlines()
            if len(lines) <= self._max_lines:
                pruned_entries.append(entry)
                continue

            omitted_count = len(lines) - (self._head_lines + self._tail_lines)
            if omitted_count <= 0:
                pruned_entries.append(entry)
                continue

            folded_head = lines[: self._head_lines]
            folded_tail = lines[-self._tail_lines :]
            marker = f"[... Truncated {omitted_count} lines of verbose execution output ...]"
            folded_content = "\n".join([*folded_head, marker, *folded_tail])

            # Estimate reduced token cost
            estimated_tokens = max(10, int(entry.token_estimate * (len(folded_content) / max(len(entry.content), 1))))

            pruned_entries.append(
                ContextLogEntry(
                    entry_id=entry.entry_id,
                    role=entry.role,
                    content=folded_content,
                    tool_call_id=entry.tool_call_id,
                    token_estimate=estimated_tokens,
                    turn_id=entry.turn_id,
                    metadata=dict(entry.metadata, was_log_pruned="true"),
                )
            )

        return pruned_entries


class DuplicateWarningDeduplicatorTransform(BaseEntryTransform):
    """Suppresses consecutive duplicate warnings or stderr output across tool results."""

    @property
    def name(self) -> str:
        """Transformer name."""
        return "DuplicateWarningDeduplicatorTransform"

    def transform(self, entries: list[ContextLogEntry]) -> list[ContextLogEntry]:
        """Eliminate immediately repeated lines within entries."""
        processed: list[ContextLogEntry] = []

        for entry in entries:
            lines = entry.content.splitlines()
            if not lines:
                processed.append(entry)
                continue

            deduped_lines: list[str] = []
            prev_line = ""
            dup_count = 0

            for line in lines:
                striped = line.strip()
                if striped and striped == prev_line:
                    dup_count += 1
                    continue
                if dup_count > 0:
                    deduped_lines.append(f"[Repeated warning suppressed x{dup_count}]")
                    dup_count = 0
                deduped_lines.append(line)
                prev_line = striped

            if dup_count > 0:
                deduped_lines.append(f"[Repeated warning suppressed x{dup_count}]")

            clean_content = "\n".join(deduped_lines)
            token_est = max(10, int(entry.token_estimate * (len(clean_content) / max(len(entry.content), 1))))

            processed.append(
                ContextLogEntry(
                    entry_id=entry.entry_id,
                    role=entry.role,
                    content=clean_content,
                    tool_call_id=entry.tool_call_id,
                    token_estimate=token_est,
                    turn_id=entry.turn_id,
                    metadata=entry.metadata,
                )
            )

        return processed
