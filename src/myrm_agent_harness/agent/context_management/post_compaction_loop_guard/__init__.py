# [INPUT]: Modules in post_compaction_loop_guard
# [OUTPUT]: Public symbols for PostCompactionToolLoopGuardSuite
# [POS]: myrm_agent_harness.agent.context_management.post_compaction_loop_guard.__init__
"""Post-Compaction Tool Loop Guard Suite (Item 331).

Protects autonomous agents from repeated tool invocation loops after context
compaction boundaries by preserving structured tool ledgers, issuing soft reminders,
and enforcing deterministic circuit breakers.
"""

from __future__ import annotations

from myrm_agent_harness.agent.context_management.post_compaction_loop_guard.compaction_tool_ledger import (
    CompactionToolLedgerExtractor,
    compute_arguments_hash,
    format_boundary_ledger_prompt,
)
from myrm_agent_harness.agent.context_management.post_compaction_loop_guard.post_compaction_loop_suite import (
    PostCompactionToolLoopGuardSuite,
)
from myrm_agent_harness.agent.context_management.post_compaction_loop_guard.reexecution_detector import (
    ReexecutionDetector,
)
from myrm_agent_harness.agent.context_management.post_compaction_loop_guard.tool_loop_types import (
    DEFAULT_HARD_TRIP_LIMIT,
    DEFAULT_MAX_SIGNATURES,
    CompactionBoundaryLedger,
    LoopDetectionAction,
    LoopGuardDecision,
    PostCompactionGuardConfig,
    RepeatedToolLoopError,
    ToolCallSignature,
)

__all__ = [
    "CompactionBoundaryLedger",
    "CompactionToolLedgerExtractor",
    "DEFAULT_HARD_TRIP_LIMIT",
    "DEFAULT_MAX_SIGNATURES",
    "LoopDetectionAction",
    "LoopGuardDecision",
    "PostCompactionGuardConfig",
    "PostCompactionToolLoopGuardSuite",
    "ReexecutionDetector",
    "RepeatedToolLoopError",
    "ToolCallSignature",
    "compute_arguments_hash",
    "format_boundary_ledger_prompt",
]
