"""Thread-safe evaluation engine for Per-Role Subagent Failure Policies (Item 35).

Evaluates mid-task failures, increments retry counters, and autonomously decides
remediation actions (restart_fresh, redeploy_specs, escalate_parent, or skip).

[INPUT]
- __future__
- logging
- threading
- types

[OUTPUT]
- logger
- RoleFailurePolicyEngine

[POS]
Thread-safe evaluation engine for Per-Role Subagent Failure Policies (Item 35).
"""

from __future__ import annotations

import logging
import threading

from .types import (
    FailureAction,
    FailureEvent,
    FailureTriggerReason,
    PolicyEvaluationDecision,
    RoleFailurePolicy,
)

logger = logging.getLogger(__name__)


class RoleFailurePolicyEngine:
    """Thread-safe evaluation engine determining autonomous remediation for failed subagents."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._policies: dict[str, RoleFailurePolicy] = {}
        self._retry_counts: dict[str, int] = {}  # task_id -> current attempt number
        self._history: list[PolicyEvaluationDecision] = []

    def register_policy(self, policy: RoleFailurePolicy) -> None:
        """Register or update a failure policy bound to a role."""
        with self._lock:
            self._policies[policy.role_key] = policy
            logger.info(
                "Registered failure policy for role '%s': primary=%s, max_retries=%d",
                policy.role_key,
                policy.primary_action,
                policy.max_retries,
            )

    def get_policy(self, role_key: str) -> RoleFailurePolicy:
        """Retrieve failure policy for a role or construct default fallback policy."""
        with self._lock:
            policy = self._policies.get(role_key)
            if not policy:
                policy = RoleFailurePolicy(
                    role_key=role_key,
                    primary_action=FailureAction.RESTART_FRESH,
                    allow_failure=False,
                    max_retries=2,
                    fallback_action=FailureAction.ESCALATE_PARENT,
                )
            return policy

    def evaluate_failure(self, event: FailureEvent) -> PolicyEvaluationDecision:
        """Evaluate a failure event against role policy and decide autonomous action."""
        with self._lock:
            policy = self._policies.get(event.role_key)
            if not policy:
                policy = RoleFailurePolicy(
                    role_key=event.role_key,
                    primary_action=FailureAction.RESTART_FRESH,
                    allow_failure=False,
                    max_retries=2,
                    fallback_action=FailureAction.ESCALATE_PARENT,
                )

            current_attempt = self._retry_counts.get(event.task_id, 0) + 1
            self._retry_counts[event.task_id] = current_attempt

            redeploy_payload: dict[str, str] = {}
            decision_action: FailureAction
            rationale: str

            # Branch 1: Role allows failure on non-fatal trigger reasons -> SKIP
            if policy.allow_failure and event.trigger_reason in (
                FailureTriggerReason.OUTPUT_SPEC_MISMATCH,
                FailureTriggerReason.TOOL_QUOTA_EXHAUSTED,
            ):
                decision_action = FailureAction.SKIP
                rationale = (
                    f"Role '{event.role_key}' allows failure on non-blocking "
                    f"reason '{event.trigger_reason.value}'; skipping subagent task."
                )

            # Branch 2: Retry attempts exceeded max_retries bound -> Fallback Escalate
            elif current_attempt > policy.max_retries:
                decision_action = policy.fallback_action
                rationale = (
                    f"Attempt {current_attempt} exceeded max retries limit ({policy.max_retries}) "
                    f"for role '{event.role_key}'; triggering fallback action '{decision_action.value}'."
                )

            # Branch 3: Execute Primary Action
            else:
                decision_action = policy.primary_action

                if decision_action == FailureAction.RESTART_FRESH:
                    template = policy.fresh_instructions_template
                    fresh_instr = (
                        template.replace("{error}", event.error_message)
                        if template
                        else (
                            f"Previous attempt encountered error: {event.error_message}. "
                            "Please restart with sanitized state and adhere to strict bounds."
                        )
                    )
                    redeploy_payload["fresh_instructions"] = fresh_instr
                    rationale = (
                        f"Attempt {current_attempt}/{policy.max_retries}: restarting role "
                        f"'{event.role_key}' with fresh instructions."
                    )

                elif decision_action == FailureAction.REDEPLOY_SPECS:
                    redeploy_payload["downgrade_model_tier"] = str(
                        policy.redeploy_model_tier_downgrade
                    ).lower()
                    redeploy_payload["remediated_spec"] = "enforce_strict_schema_and_tight_budget"
                    rationale = (
                        f"Attempt {current_attempt}/{policy.max_retries}: redeploying role "
                        f"'{event.role_key}' with adjusted specifications."
                    )

                elif decision_action == FailureAction.SKIP:
                    rationale = f"Primary policy for role '{event.role_key}' is to skip task execution."

                else:
                    rationale = (
                        f"Primary policy for role '{event.role_key}' escalates immediately to parent."
                    )

            decision = PolicyEvaluationDecision(
                event_id=event.event_id,
                task_id=event.task_id,
                role_key=event.role_key,
                action=decision_action,
                attempt_number=current_attempt,
                max_retries=policy.max_retries,
                rationale=rationale,
                redeploy_payload=redeploy_payload,
            )

            self._history.append(decision)
            logger.info(
                "Evaluated failure event '%s' (task: %s, role: %s) -> Action: %s (attempt %d/%d)",
                event.event_id,
                event.task_id,
                event.role_key,
                decision_action,
                current_attempt,
                policy.max_retries,
            )
            return decision

    def reset_retry_count(self, task_id: str) -> None:
        """Reset retry attempt counter for a specific task."""
        with self._lock:
            self._retry_counts.pop(task_id, None)

    def get_history(
        self,
        task_id: str | None = None,
        limit: int = 50,
    ) -> tuple[PolicyEvaluationDecision, ...]:
        """Retrieve historical failure decisions filtered by task_id."""
        with self._lock:
            records = [d for d in self._history if task_id is None or d.task_id == task_id]
            return tuple(records[-limit:])

    def clear(self) -> None:
        """Purge all policies, counters, and history."""
        with self._lock:
            self._policies.clear()
            self._retry_counts.clear()
            self._history.clear()
