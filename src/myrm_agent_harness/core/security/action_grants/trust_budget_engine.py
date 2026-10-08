"""Trust budget engine to counteract approval fatigue with deterministic convergence."""

from __future__ import annotations

import time

from .types import TrustBudgetRecord


class TrustBudgetEngine:
    """Tracks continuous user approval trust budgets and executes monotonic demotions.

    Trust budgets accumulate only through deterministic user approval facts and
    instantly collapse to zero upon correction, undo, or revocation.
    """

    def __init__(self, default_suggestion_threshold: int = 3) -> None:
        self._budgets: dict[tuple[str, str, str], TrustBudgetRecord] = {}
        self._default_threshold: int = default_suggestion_threshold

    def _get_key(self, agent_id: str, service: str, action: str) -> tuple[str, str, str]:
        return (agent_id.strip(), service.strip().lower(), action.strip().lower())

    def record_approval(
        self,
        agent_id: str,
        service: str,
        action: str,
    ) -> TrustBudgetRecord:
        """Record a successful user approval without correction, incrementing trust budget."""
        key = self._get_key(agent_id, service, action)
        existing = self._budgets.get(key)
        new_consecutive = 1 if existing is None else existing.consecutive_approvals + 1

        record = TrustBudgetRecord(
            agent_id=agent_id,
            service=service.strip().lower(),
            action=action.strip().lower(),
            consecutive_approvals=new_consecutive,
            is_locked_to_ask=False,
            last_demoted_at=existing.last_demoted_at if existing else None,
            demotion_reason=None,
        )
        self._budgets[key] = record
        return record

    def record_demotion(
        self,
        agent_id: str,
        service: str,
        action: str,
        reason: str = "User corrected or revoked action",
    ) -> TrustBudgetRecord:
        """Immediately collapse trust budget to zero and lock back to Ask state."""
        key = self._get_key(agent_id, service, action)
        record = TrustBudgetRecord(
            agent_id=agent_id,
            service=service.strip().lower(),
            action=action.strip().lower(),
            consecutive_approvals=0,
            is_locked_to_ask=True,
            last_demoted_at=time.time(),
            demotion_reason=reason,
        )
        self._budgets[key] = record
        return record

    def get_budget(
        self,
        agent_id: str,
        service: str,
        action: str,
    ) -> TrustBudgetRecord:
        """Retrieve the trust budget record for the given agent and action tuple."""
        key = self._get_key(agent_id, service, action)
        record = self._budgets.get(key)
        if record is None:
            return TrustBudgetRecord(
                agent_id=agent_id,
                service=service.strip().lower(),
                action=action.strip().lower(),
                consecutive_approvals=0,
                is_locked_to_ask=False,
            )
        return record

    def should_suggest_grant(
        self,
        agent_id: str,
        service: str,
        action: str,
        threshold: int | None = None,
    ) -> bool:
        """Check whether trust budget has accumulated enough approvals to suggest a grant."""
        budget = self.get_budget(agent_id, service, action)
        if budget.is_locked_to_ask:
            return False
        effective_threshold = threshold if threshold is not None else self._default_threshold
        return budget.consecutive_approvals >= effective_threshold

    def unlock_ask(
        self,
        agent_id: str,
        service: str,
        action: str,
    ) -> TrustBudgetRecord:
        """Explicitly clear the Ask lock without restoring prior consecutive count."""
        key = self._get_key(agent_id, service, action)
        existing = self._budgets.get(key)
        record = TrustBudgetRecord(
            agent_id=agent_id,
            service=service.strip().lower(),
            action=action.strip().lower(),
            consecutive_approvals=0,
            is_locked_to_ask=False,
            last_demoted_at=existing.last_demoted_at if existing else None,
            demotion_reason=None,
        )
        self._budgets[key] = record
        return record
