"""Shared Context Token Budget Governor conforming to Item 52.

Manages shared primary model token ceilings, per-role budget allocation,
fan-out precheck, and routing overhead vs execution payload Doctor alerts.

[INPUT]
- __future__
- threading
- time
- uuid

[OUTPUT]
- SharedTokenBudgetGovernor

[POS]
Shared Context Token Budget Governor conforming to Item 52.
"""

from __future__ import annotations

import threading
import time
import uuid

from myrm_agent_harness.agent.sub_agents.token_budget_governance.types import (
    ConsumptionCategory,
    ConsumptionRecord,
    DoctorNudgeAlert,
    GovernancePrecheckResult,
    MetadataDict,
    NudgeSeverity,
    RoleBudgetSpec,
    SharedTokenBudgetSnapshot,
)


class SharedTokenBudgetGovernor:
    """Governor enforcing token budget ceilings across multiple subagents sharing a model."""

    def __init__(
        self,
        session_id: str,
        primary_model: str = "claude-3-5-sonnet",
        shared_token_ceiling: int = 100_000,
    ) -> None:
        self.session_id: str = session_id
        self.primary_model: str = primary_model
        self.shared_token_ceiling: int = shared_token_ceiling

        self._lock: threading.Lock = threading.Lock()
        self._role_budgets: dict[str, RoleBudgetSpec] = {}
        self._role_usage: dict[str, int] = {}
        self._records: list[ConsumptionRecord] = []
        self._handoff_count: int = 0
        self._alerts: list[DoctorNudgeAlert] = []

    def register_role_budget(self, spec: RoleBudgetSpec) -> None:
        """Register or update a per-role token budget specification."""
        with self._lock:
            self._role_budgets[spec.role_name] = spec
            if spec.role_name not in self._role_usage:
                self._role_usage[spec.role_name] = 0

    def precheck_fanout(
        self,
        role_name: str,
        estimated_tokens: int,
    ) -> GovernancePrecheckResult:
        """Evaluate if fanning out or dispatching a turn to role_name exceeds budget ceilings."""
        with self._lock:
            total_spent = sum(r.total_tokens for r in self._records)
            remaining_shared = max(0, self.shared_token_ceiling - total_spent)

            # 1. Global shared model ceiling precheck
            if (total_spent + estimated_tokens) > self.shared_token_ceiling:
                return GovernancePrecheckResult(
                    passed=False,
                    requested_tokens=estimated_tokens,
                    remaining_budget=remaining_shared,
                    reason=(
                        f"Global shared ceiling exceeded: requested {estimated_tokens} tokens, "
                        f"only {remaining_shared} remaining under {self.shared_token_ceiling} ceiling."
                    ),
                )

            # 2. Per-role budget precheck if declared
            if role_name in self._role_budgets:
                spec = self._role_budgets[role_name]
                current_role_spent = self._role_usage.get(role_name, 0)
                remaining_role = max(0, spec.token_ceiling - current_role_spent)

                if (
                    current_role_spent + estimated_tokens > spec.token_ceiling
                    and not spec.allow_overflow
                ):
                    return GovernancePrecheckResult(
                        passed=False,
                        requested_tokens=estimated_tokens,
                        remaining_budget=remaining_role,
                        reason=(
                            f"Per-role ceiling exceeded for '{role_name}': requested {estimated_tokens} "
                            f"tokens, only {remaining_role} remaining under {spec.token_ceiling} ceiling. "
                            f"Triggered stop condition: '{spec.stop_condition}'."
                        ),
                    )

            return GovernancePrecheckResult(
                passed=True,
                requested_tokens=estimated_tokens,
                remaining_budget=remaining_shared,
                reason="Precheck passed: within shared and role-scoped ceilings.",
            )

    def record_consumption(
        self,
        agent_role: str,
        category: ConsumptionCategory,
        prompt_tokens: int,
        completion_tokens: int,
        metadata: MetadataDict | None = None,
    ) -> ConsumptionRecord:
        """Record token consumption and evaluate routing overhead alerts."""
        with self._lock:
            total_tokens = prompt_tokens + completion_tokens
            now = time.time()
            record_id = f"rec-{uuid.uuid4().hex[:8]}"

            # Check if this represents a handoff event
            meta = metadata or {}
            if category == ConsumptionCategory.ROUTING_OVERHEAD or meta.get("is_handoff"):
                self._handoff_count += 1

            # Update role usage
            self._role_usage[agent_role] = self._role_usage.get(agent_role, 0) + total_tokens

            record = ConsumptionRecord(
                record_id=record_id,
                agent_role=agent_role,
                category=category,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                timestamp=now,
                metadata=meta,
            )
            self._records.append(record)

            # Evaluate Doctor nudges
            self._evaluate_doctor_nudge_locked()
            return record

    def _evaluate_doctor_nudge_locked(
        self,
        threshold_routing_ratio: float = 0.35,
        max_handoffs: int = 5,
    ) -> None:
        """Internal evaluator for Doctor budget alerts."""
        total_spent = sum(r.total_tokens for r in self._records)
        routing_spent = sum(
            r.total_tokens
            for r in self._records
            if r.category == ConsumptionCategory.ROUTING_OVERHEAD
        )
        routing_ratio = (routing_spent / total_spent) if total_spent > 0 else 0.0

        new_alerts: list[DoctorNudgeAlert] = []

        # Alert 1: High routing overhead ratio
        if total_spent >= 2000 and routing_ratio > threshold_routing_ratio:
            new_alerts.append(
                DoctorNudgeAlert(
                    alert_id=f"alert-routing-{uuid.uuid4().hex[:6]}",
                    severity=NudgeSeverity.WARNING,
                    message=(
                        f"Routing overhead is {routing_ratio * 100:.1f}% of total tokens "
                        f"({routing_spent}/{total_spent}), exceeding {threshold_routing_ratio * 100:.0f}% threshold."
                    ),
                    handoff_count=self._handoff_count,
                    routing_ratio=round(routing_ratio, 4),
                    suggested_action="Consolidate routing prompts or bypass intermediate delegators.",
                )
            )

        # Alert 2: Excessive handoffs causing churn
        if self._handoff_count >= max_handoffs:
            new_alerts.append(
                DoctorNudgeAlert(
                    alert_id=f"alert-handoff-{uuid.uuid4().hex[:6]}",
                    severity=NudgeSeverity.CRITICAL,
                    message=(
                        f"Repetitive agent handoffs detected ({self._handoff_count} >= {max_handoffs}). "
                        "Subagents are repeatedly bouncing tasks without producing execution payload."
                    ),
                    handoff_count=self._handoff_count,
                    routing_ratio=round(routing_ratio, 4),
                    suggested_action="Halt delegation loop and lock primary model directly to specialist.",
                )
            )

        self._alerts = new_alerts

    def evaluate_doctor_nudge(
        self,
        threshold_routing_ratio: float = 0.35,
        max_handoffs: int = 5,
    ) -> list[DoctorNudgeAlert]:
        """Public trigger to re-evaluate and return Doctor alerts."""
        with self._lock:
            self._evaluate_doctor_nudge_locked(
                threshold_routing_ratio=threshold_routing_ratio,
                max_handoffs=max_handoffs,
            )
            return list(self._alerts)

    def get_snapshot(self) -> SharedTokenBudgetSnapshot:
        """Generate a global snapshot of budget status, routing breakdown, and active alerts."""
        with self._lock:
            total_spent = sum(r.total_tokens for r in self._records)
            routing_spent = sum(
                r.total_tokens
                for r in self._records
                if r.category == ConsumptionCategory.ROUTING_OVERHEAD
            )
            execution_spent = total_spent - routing_spent
            routing_ratio = (routing_spent / total_spent) if total_spent > 0 else 0.0

            return SharedTokenBudgetSnapshot(
                session_id=self.session_id,
                primary_model=self.primary_model,
                shared_token_ceiling=self.shared_token_ceiling,
                total_tokens_spent=total_spent,
                routing_tokens_spent=routing_spent,
                execution_tokens_spent=execution_spent,
                routing_ratio=round(routing_ratio, 4),
                role_budgets=dict(self._role_budgets),
                role_usage=dict(self._role_usage),
                active_alerts=list(self._alerts),
            )

    def reset(self) -> None:
        """Reset governor state."""
        with self._lock:
            self._role_budgets.clear()
            self._role_usage.clear()
            self._records.clear()
            self._handoff_count = 0
            self._alerts.clear()
