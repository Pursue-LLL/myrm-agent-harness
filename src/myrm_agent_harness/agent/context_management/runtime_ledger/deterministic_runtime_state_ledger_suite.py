# [INPUT]: DeterministicLedgerCompiler, LedgerInjectionResult, LedgerUpdatePolicy, QuotaConstraint, RuntimeLedgerConfig, RuntimeStateSnapshot, TailLedgerInjector, TodoProgress
# [OUTPUT]: DeterministicRuntimeStateLedgerInjectionSuite
# [POS]: agent/context_management/runtime_ledger/deterministic_runtime_state_ledger_suite.py

"""End-to-end facade orchestrating deterministic runtime state ledger compilation and tail injection.

[INPUT]
- Domain models: QuotaConstraint, RuntimeStateSnapshot, TodoProgress, LedgerInjectionResult, LedgerUpdatePolicy.
- Component engines: DeterministicLedgerCompiler, TailLedgerInjector.
- RuntimeLedgerConfig: Settings.

[OUTPUT]
- DeterministicRuntimeStateLedgerInjectionSuite: Unified top-level facade.

[POS]
Main entry point in agent/context_management/runtime_ledger implementing the <agent_status> dashboard paradigm.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from .deterministic_ledger_compiler import DeterministicLedgerCompiler
from .runtime_ledger_types import (
    LedgerInjectionResult,
    LedgerUpdatePolicy,
    QuotaConstraint,
    RuntimeLedgerConfig,
    RuntimeStateSnapshot,
    TodoProgress,
)
from .tail_ledger_injector import TailLedgerInjector


class DeterministicRuntimeStateLedgerInjectionSuite:
    """Unified facade managing deterministic status computation, constraint tracking, and cache-friendly tail mounting."""

    def __init__(
        self,
        config: RuntimeLedgerConfig | None = None,
        compiler: DeterministicLedgerCompiler | None = None,
        injector: TailLedgerInjector | None = None,
    ) -> None:
        self._config = config or RuntimeLedgerConfig()
        self._compiler = compiler or DeterministicLedgerCompiler(self._config)
        self._injector = injector or TailLedgerInjector(self._config)

    @property
    def config(self) -> RuntimeLedgerConfig:
        return self._config

    def compile_and_inject(
        self,
        prompt_text: str,
        session_id: str,
        turn_index: int,
        tool_call_counts: Mapping[str, int] | None = None,
        constraints: Sequence[QuotaConstraint] | None = None,
        todos: Sequence[TodoProgress] | None = None,
        recent_milestones: Sequence[str] | None = None,
        timestamp_iso: str | None = None,
    ) -> tuple[str, LedgerInjectionResult, RuntimeStateSnapshot]:
        """Deterministically compiles runtime state snapshot and mounts <agent_status> tag at prompt tail."""
        snapshot = self._compiler.compile_snapshot(
            session_id=session_id,
            turn_index=turn_index,
            tool_call_counts=tool_call_counts,
            constraints=constraints,
            todos=todos,
            recent_milestones=recent_milestones,
            timestamp_iso=timestamp_iso,
        )

        expanded_text, result = self._injector.inject_into_text(
            base_text=prompt_text,
            snapshot=snapshot,
        )

        return expanded_text, result, snapshot

    def count_and_inject_from_messages(
        self,
        messages: Sequence[Mapping[str, str | Sequence[Mapping[str, str]]]],
        base_prompt: str,
        session_id: str,
        turn_index: int,
        constraints: Sequence[QuotaConstraint] | None = None,
        todos: Sequence[TodoProgress] | None = None,
        recent_milestones: Sequence[str] | None = None,
    ) -> tuple[str, LedgerInjectionResult, RuntimeStateSnapshot]:
        """Counts tool calls directly from message records and attaches status block to prompt tail."""
        counts = self._compiler.count_tool_calls_from_messages(messages)
        return self.compile_and_inject(
            prompt_text=base_prompt,
            session_id=session_id,
            turn_index=turn_index,
            tool_call_counts=counts,
            constraints=constraints,
            todos=todos,
            recent_milestones=recent_milestones,
        )

    def render_raw_tag(self, snapshot: RuntimeStateSnapshot) -> str:
        """Renders raw status tag string without mounting into prompt."""
        return self._injector.render_status_tag(snapshot)

    def evaluate_violations(self, snapshot: RuntimeStateSnapshot) -> Sequence[str]:
        """Checks for exhausted constraints and returns human-readable warning banners."""
        return self._compiler.evaluate_constraint_violations(snapshot)
