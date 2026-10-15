# -*- coding: utf-8 -*-
"""MoA Reasoning Effort Governor.

Dynamically allocates reasoning intensity (low, medium, max, ultra) and token
budgets across different Mixture-of-Agents (MoA) roles to optimize output quality
while keeping token consumption strictly governed.
"""

from threading import Lock
from typing import Dict

from .types import ReasoningEffortLevel

ROLE_EFFORT_MAP: Dict[str, ReasoningEffortLevel] = {
    "triage": ReasoningEffortLevel.LOW,
    "scout": ReasoningEffortLevel.LOW,
    "summarizer": ReasoningEffortLevel.LOW,
    "retriever": ReasoningEffortLevel.MEDIUM,
    "researcher": ReasoningEffortLevel.MEDIUM,
    "analyst": ReasoningEffortLevel.MEDIUM,
    "architect": ReasoningEffortLevel.MAX,
    "code_auditor": ReasoningEffortLevel.MAX,
    "planner": ReasoningEffortLevel.MAX,
    "deep_reasoner": ReasoningEffortLevel.ULTRA,
    "verifier": ReasoningEffortLevel.ULTRA,
    "security_auditor": ReasoningEffortLevel.ULTRA,
}

EFFORT_TOKEN_BUDGETS: Dict[ReasoningEffortLevel, int] = {
    ReasoningEffortLevel.LOW: 1024,
    ReasoningEffortLevel.MEDIUM: 4096,
    ReasoningEffortLevel.MAX: 16384,
    ReasoningEffortLevel.ULTRA: 32768,
}


class MoAReasoningEffortGovernor:
    """Allocates reasoning intensity and enforces token budgets per subagent role."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._custom_mappings: Dict[str, ReasoningEffortLevel] = {}
        self._spent_budgets: Dict[str, int] = {}

    def set_role_effort(self, role: str, effort: ReasoningEffortLevel) -> None:
        """Override or configure reasoning effort for a specific role."""
        with self._lock:
            self._custom_mappings[role.lower()] = effort

    def resolve_effort(self, role: str) -> ReasoningEffortLevel:
        """Resolve reasoning effort level for a role, defaulting to MEDIUM."""
        role_key = role.lower().strip()
        with self._lock:
            if role_key in self._custom_mappings:
                return self._custom_mappings[role_key]
        return ROLE_EFFORT_MAP.get(role_key, ReasoningEffortLevel.MEDIUM)

    def get_token_budget(self, effort: ReasoningEffortLevel) -> int:
        """Get allocated thinking token budget for a reasoning effort level."""
        return EFFORT_TOKEN_BUDGETS.get(effort, 4096)

    def record_usage(self, task_id: str, tokens: int) -> int:
        """Record reasoning token usage for a task and return cumulative tokens."""
        with self._lock:
            current = self._spent_budgets.get(task_id, 0) + tokens
            self._spent_budgets[task_id] = current
            return current

    def get_cumulative_usage(self, task_id: str) -> int:
        """Get cumulative reasoning tokens consumed by a task."""
        with self._lock:
            return self._spent_budgets.get(task_id, 0)
