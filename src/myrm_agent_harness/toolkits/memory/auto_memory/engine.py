# [POS]: src/myrm_agent_harness/toolkits/memory/auto_memory/engine.py
# [INPUT]: SessionActivitySnapshot, Sequence[dict[str, str]], AutoMemoryBudgetPolicy, AutoMemoryGate, SixDimensionalExtractor
# [OUTPUT]: IdleAndBudgetGatedAutoMemoryEngine

"""Unified coordination engine for idle and budget-gated auto-memory consolidation.

Coordinates inactivity timing, turn thresholds, token budget checks,
and 6-dimensional structured memory artifact extraction.

[INPUT]
- toolkits.memory.auto_memory.extractor::SixDimensionalExtractor (POS: Six-dimensional structured artifact
  extractor for session memory.)
- toolkits.memory.auto_memory.gate::AutoMemoryGate (POS: Dual-gate evaluation engine enforcing turn count and
  token budget thresholds.)
- toolkits.memory.auto_memory.models::AutoMemoryBudgetPolicy, AutoMemoryExtractionResult,
  AutoMemoryGatingDecision, SessionActivitySnapshot, SixDimensionalMemorySlice (POS: Domain models for Idle
  and Budget Gated Auto-Memory Engine Suite (Item 123 P1).)

[OUTPUT]
- IdleAndBudgetGatedAutoMemoryEngine: Orchestrates idle detection, dual-gating, and six-dimensional memory
  extraction.

[POS]
Unified coordination engine for idle and budget-gated auto-memory consolidation.
"""

from __future__ import annotations

from collections.abc import Sequence

from myrm_agent_harness.toolkits.memory.auto_memory.extractor import SixDimensionalExtractor
from myrm_agent_harness.toolkits.memory.auto_memory.gate import AutoMemoryGate
from myrm_agent_harness.toolkits.memory.auto_memory.models import (
    AutoMemoryBudgetPolicy,
    AutoMemoryExtractionResult,
    AutoMemoryGatingDecision,
    SessionActivitySnapshot,
    SixDimensionalMemorySlice,
)


class IdleAndBudgetGatedAutoMemoryEngine:
    """Orchestrates idle detection, dual-gating, and six-dimensional memory extraction."""

    def __init__(
        self,
        gate: AutoMemoryGate | None = None,
        extractor: SixDimensionalExtractor | None = None,
    ) -> None:
        self._gate = gate or AutoMemoryGate()
        self._extractor = extractor or SixDimensionalExtractor()

    def evaluate_eligibility(
        self,
        snapshot: SessionActivitySnapshot,
        policy: AutoMemoryBudgetPolicy | None = None,
        total_message_chars: int = 0,
        now_ts: float | None = None,
        force_ignore_idle: bool = False,
    ) -> tuple[bool, AutoMemoryGatingDecision, str]:
        """Evaluate whether a session qualifies for automated memory consolidation."""
        active_policy = policy or AutoMemoryBudgetPolicy()
        return self._gate.evaluate(
            snapshot=snapshot,
            policy=active_policy,
            total_message_chars=total_message_chars,
            now_ts=now_ts,
            force_ignore_idle=force_ignore_idle,
        )

    def process_session(
        self,
        snapshot: SessionActivitySnapshot,
        messages: Sequence[dict[str, str]],
        policy: AutoMemoryBudgetPolicy | None = None,
        now_ts: float | None = None,
        force_ignore_idle: bool = False,
    ) -> AutoMemoryExtractionResult:
        """Evaluate gating criteria and extract 6D memory slice if eligible."""
        active_policy = policy or AutoMemoryBudgetPolicy()
        total_chars = sum(len(m.get("content", "")) for m in messages)

        is_eligible, decision, reason = self._gate.evaluate(
            snapshot=snapshot,
            policy=active_policy,
            total_message_chars=total_chars,
            now_ts=now_ts,
            force_ignore_idle=force_ignore_idle,
        )

        if not is_eligible:
            return AutoMemoryExtractionResult(
                decision=decision,
                is_eligible=False,
                reason=reason,
                memory_slice=None,
                tokens_billed_for_extraction=0,
            )

        # Extraction phase
        memory_slice: SixDimensionalMemorySlice = self._extractor.extract_slice_heuristic(
            messages=messages,
            session_id=snapshot.session_id,
            workspace_path=snapshot.workspace_path,
        )

        return AutoMemoryExtractionResult(
            decision=AutoMemoryGatingDecision.ACCEPTED,
            is_eligible=True,
            reason=reason,
            memory_slice=memory_slice,
            tokens_billed_for_extraction=0,
        )
