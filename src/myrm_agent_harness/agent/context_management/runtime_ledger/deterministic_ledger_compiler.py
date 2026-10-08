# [INPUT]: QuotaConstraint, RuntimeLedgerConfig, RuntimeStateSnapshot, TodoProgress
# [OUTPUT]: DeterministicLedgerCompiler
# [POS]: agent/context_management/runtime_ledger/deterministic_ledger_compiler.py

"""Deterministic compiler aggregating runtime tool call counters, quota constraints, and task progression.

[INPUT]
- QuotaConstraint, RuntimeStateSnapshot, TodoProgress: Domain models.
- RuntimeLedgerConfig: Settings.

[OUTPUT]
- DeterministicLedgerCompiler: Pure deterministic calculator producing structured state snapshots without LLM.

[POS]
Data collection and deterministic calculation layer in runtime state ledger suite.
"""

from __future__ import annotations

import datetime
from typing import Mapping, Sequence

from .runtime_ledger_types import (
    QuotaConstraint,
    RuntimeLedgerConfig,
    RuntimeStateSnapshot,
    TodoProgress,
)


class DeterministicLedgerCompiler:
    """Aggregates tool usages, checks constraint budgets, and compiles immutable RuntimeStateSnapshot."""

    def __init__(self, config: RuntimeLedgerConfig | None = None) -> None:
        self._config = config or RuntimeLedgerConfig()

    def compile_snapshot(
        self,
        session_id: str,
        turn_index: int,
        tool_call_counts: Mapping[str, int] | None = None,
        constraints: Sequence[QuotaConstraint] | None = None,
        todos: Sequence[TodoProgress] | None = None,
        recent_milestones: Sequence[str] | None = None,
        timestamp_iso: str | None = None,
    ) -> RuntimeStateSnapshot:
        """Constructs an immutable status snapshot deterministically from known execution variables."""
        now_str = timestamp_iso or datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        counts = dict(tool_call_counts or {})
        active_constraints = tuple(constraints or ())
        active_todos = tuple(todos or ())
        milestones = tuple(recent_milestones or ())

        return RuntimeStateSnapshot(
            session_id=session_id,
            turn_index=turn_index,
            tool_call_counts=counts,
            constraints=active_constraints,
            todos=active_todos,
            current_timestamp_iso=now_str,
            recent_milestones=milestones,
        )

    def count_tool_calls_from_messages(
        self,
        messages: Sequence[Mapping[str, str | Sequence[Mapping[str, str]]]],
    ) -> dict[str, int]:
        """Scans message history and deterministically counts tool invocations per tool name."""
        counts: dict[str, int] = {}
        for msg in messages:
            tool_calls = msg.get("tool_calls")
            if isinstance(tool_calls, (list, tuple)):
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        # Support OpenAI format {"function": {"name": ...}} and flat {"name": ...}
                        fn_obj = tc.get("function")
                        if isinstance(fn_obj, dict) and "name" in fn_obj:
                            name = str(fn_obj["name"])
                        else:
                            name = str(tc.get("name", "unknown_tool"))
                        counts[name] = counts.get(name, 0) + 1
        return counts

    def evaluate_constraint_violations(
        self,
        snapshot: RuntimeStateSnapshot,
    ) -> Sequence[str]:
        """Identifies exhausted constraints and returns warning notices to inject into steering."""
        violations: list[str] = []
        for c in snapshot.constraints:
            if c.is_exhausted:
                violations.append(
                    f"⚠️ [QUOTA EXHAUSTED] {c.name}: used {c.used_count}/{c.max_limit} {c.unit}. Further invocations FORBIDDEN."
                )
        return tuple(violations)
