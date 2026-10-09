# [INPUT]: BaseMessage from langchain_core, CompactionToolLedgerExtractor, format_boundary_ledger_prompt from compaction_tool_ledger, ReexecutionDetector from reexecution_detector, types from tool_loop_types
# [OUTPUT]: PostCompactionToolLoopGuardSuite
# [POS]: myrm_agent_harness.agent.context_management.post_compaction_loop_guard.post_compaction_loop_suite
"""Unified facade suite for Post-Compaction Tool Loop Guard (Item 331).

Coordinates compaction boundary tool ledger capture, prompt evidence block formatting,
and tool re-execution loop detection with deterministic circuit breakers.
"""

from __future__ import annotations

import threading
from typing import Final
from langchain_core.messages import BaseMessage

from myrm_agent_harness.agent.context_management.post_compaction_loop_guard.compaction_tool_ledger import (
    CompactionToolLedgerExtractor,
    format_boundary_ledger_prompt,
)
from myrm_agent_harness.agent.context_management.post_compaction_loop_guard.reexecution_detector import (
    ReexecutionDetector,
)
from myrm_agent_harness.agent.context_management.post_compaction_loop_guard.tool_loop_types import (
    CompactionBoundaryLedger,
    LoopGuardDecision,
    PostCompactionGuardConfig,
)


class PostCompactionToolLoopGuardSuite:
    """Industrial suite providing comprehensive protection against tool execution loops after compaction."""

    def __init__(self, config: PostCompactionGuardConfig | None = None) -> None:
        self._lock = threading.RLock()
        self._config: PostCompactionGuardConfig = config or PostCompactionGuardConfig()
        self._detector: Final[ReexecutionDetector] = ReexecutionDetector(config=self._config)
        self._active_ledgers: dict[str, CompactionBoundaryLedger] = {}

    @property
    def detector(self) -> ReexecutionDetector:
        """Underlying tool re-execution detector engine."""
        return self._detector

    @property
    def config(self) -> PostCompactionGuardConfig:
        """Active suite configuration."""
        with self._lock:
            return self._config

    def capture_compaction_boundary(
        self,
        session_id: str,
        messages: list[BaseMessage],
        compaction_turn_index: int,
    ) -> tuple[CompactionBoundaryLedger, str]:
        """Capture recent tool signatures prior to compaction and generate prompt injection text.

        Args:
            session_id: Conversation session identifier.
            messages: Full message sequence before compaction.
            compaction_turn_index: Current conversation turn index.

        Returns:
            tuple of (CompactionBoundaryLedger, formatted_prompt_evidence_block)
        """
        with self._lock:
            ledger = CompactionToolLedgerExtractor.extract_ledger(
                session_id=session_id,
                messages=messages,
                compaction_turn_index=compaction_turn_index,
                max_signatures=self._config.max_retained_signatures,
            )
            self._active_ledgers[session_id] = ledger
            self._detector.register_boundary_ledger(ledger)
            evidence_prompt = format_boundary_ledger_prompt(ledger)
            return ledger, evidence_prompt

    def intercept_tool_call(
        self,
        session_id: str,
        tool_name: str,
        arguments: dict[str, str | int | float | bool | list[str] | dict[str, str] | None] | str,
        current_turn: int,
        raise_on_trip: bool = False,
    ) -> LoopGuardDecision:
        """Inspect impending tool call, evaluating if it repeats a call from the boundary ledger.

        Args:
            session_id: Session identifier.
            tool_name: Name of tool to execute.
            arguments: Tool arguments payload.
            current_turn: Current conversation turn.
            raise_on_trip: If True, raise RepeatedToolLoopError upon hard trip.

        Returns:
            LoopGuardDecision with ALLOW, REMIND_IN_CONTEXT, or TRIPPED_CIRCUIT_BREAKER.
        """
        return self._detector.evaluate_tool_call(
            session_id=session_id,
            tool_name=tool_name,
            arguments=arguments,
            current_turn=current_turn,
            raise_on_trip=raise_on_trip,
        )

    def get_active_ledger(self, session_id: str) -> CompactionBoundaryLedger | None:
        """Retrieve active boundary ledger for session."""
        with self._lock:
            return self._active_ledgers.get(session_id)

    def reset_session(self, session_id: str) -> None:
        """Clear all active ledgers and loop counters for session."""
        with self._lock:
            self._active_ledgers.pop(session_id, None)
            self._detector.reset_session(session_id)
