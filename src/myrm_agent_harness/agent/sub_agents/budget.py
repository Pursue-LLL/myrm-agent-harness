"""Delegation budget state for scoped subagent runtime.

[INPUT]
- agent.sub_agents.types::SubagentConfig (POS: Subagent subsystem core type definitions. Defines all subagent-related data types, enums, and protocols.)

[OUTPUT]
- DelegationBudgetExceededError: Raised when a delegation tree exceeds runtime budget.
- DelegationBudgetState: Per-root-run descendant budget counter shared by child managers.

[POS]
Delegation budget guard. Tracks descendant spawn count for a root agent run without business-layer coupling.
"""

from __future__ import annotations

from dataclasses import dataclass


class DelegationBudgetExceededError(Exception):
    """Raised when a subagent delegation budget would be exceeded."""


@dataclass(slots=True)
class DelegationBudgetState:
    """Shared descendant budget for one root delegation tree."""

    max_descendants: int = 20
    spawned_descendants: int = 0

    def reserve(self, count: int = 1) -> None:
        """Reserve descendant slots before spawning new subagents."""
        if count < 1:
            return
        next_count = self.spawned_descendants + count
        if next_count > self.max_descendants:
            raise DelegationBudgetExceededError(
                f"Delegation budget exceeded: requested {next_count}/{self.max_descendants} descendants"
            )
        self.spawned_descendants = next_count

    def snapshot(self) -> dict[str, int]:
        """Return a serializable budget snapshot for events and errors."""
        return {
            "max_descendants": self.max_descendants,
            "spawned_descendants": self.spawned_descendants,
        }
