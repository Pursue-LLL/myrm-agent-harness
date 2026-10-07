"""Type definitions for model-free deterministic tool result pruner and zero-cost context compactor.

Defines configuration options, audit line items, and compaction report metrics
for zero-LLM-cost deterministic context token pressure mitigation.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- ModelFreePrunerConfig: Configuration governing model-free deterministic tool output compaction.
- PruningAuditItem: Audit record of a single tool message evaluated during deterministic pruning.
- ModelFreeCompactionReport: Overall execution report and token savings metrics from deterministic
  compaction.

[POS]
Type definitions for model-free deterministic tool result pruner and zero-cost context compactor.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelFreePrunerConfig:
    """Configuration governing model-free deterministic tool output compaction."""

    recent_immune_turns: int = 2
    readonly_tool_names: frozenset[str] = field(
        default_factory=lambda: frozenset({
            "read_file",
            "view_file",
            "list_dir",
            "grep_search",
            "search_web",
            "git_status",
            "read_url_content",
            "fetch",
        })
    )
    error_tail_lines: int = 10
    min_prune_char_threshold: int = 300


@dataclass(frozen=True)
class PruningAuditItem:
    """Audit record of a single tool message evaluated during deterministic pruning."""

    message_id: str
    tool_name: str
    original_chars: int
    pruned_chars: int
    was_error: bool
    strategy_applied: str  # "folded_readonly", "retained_error_tail", "skipped_immune", "skipped_small"


@dataclass(frozen=True)
class ModelFreeCompactionReport:
    """Overall execution report and token savings metrics from deterministic compaction."""

    total_messages_scanned: int
    tools_pruned_count: int
    original_total_chars: int
    compacted_total_chars: int
    chars_freed: int
    tokens_freed_estimate: int
    savings_ratio: float
    audit_items: list[PruningAuditItem] = field(default_factory=list)
