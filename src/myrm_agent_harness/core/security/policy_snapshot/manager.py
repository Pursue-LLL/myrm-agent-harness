"""Policy Snapshot Manager and Dual-Track Update Engine.

Guarantees:
1. In-flight task policy snapshot isolation: in-flight tasks strictly run on their pinned
   policy version, shielded from ordinary background administrative changes.
2. Dual-track updates:
   - Soft Update: applies only to subsequent new tasks without disrupting in-flight runs.
   - Emergency Hot Kill: immediately intercepts high-risk tools across in-flight executions.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from myrm_agent_harness.core.security.policy_snapshot.types import (
    EmergencyHotKillBlockedError,
    EmergencyHotKillDirective,
    ExecutionPolicySnapshot,
    JsonScalar,
    PolicyDriftViolationError,
    TaskPolicyBinding,
)


def compute_policy_hash(
    version_number: int,
    prompt_template_hash: str,
    allowed_tools: Sequence[str],
    governance_rules: Mapping[str, JsonScalar],
) -> str:
    """Compute canonical SHA-256 fingerprint for a policy snapshot."""
    payload = {
        "version_number": version_number,
        "prompt_template_hash": prompt_template_hash,
        "allowed_tools": sorted(allowed_tools),
        "governance_rules": dict(sorted(governance_rules.items())),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class PolicySnapshotManager:
    """Manages policy snapshots, in-flight pinning, and dual-track updates."""

    def __init__(
        self,
        initial_prompt_template: str = "Standard System Prompt",
        initial_allowed_tools: Sequence[str] = ("read_file", "list_dir"),
        initial_governance_rules: Mapping[str, JsonScalar] | None = None,
    ) -> None:
        rules = dict(initial_governance_rules) if initial_governance_rules is not None else {}
        prompt_hash = hashlib.sha256(initial_prompt_template.encode("utf-8")).hexdigest()
        policy_hash = compute_policy_hash(1, prompt_hash, initial_allowed_tools, rules)

        self._snapshots: list[ExecutionPolicySnapshot] = []
        initial_snapshot = ExecutionPolicySnapshot(
            snapshot_id=f"snap-{uuid.uuid4().hex[:10]}",
            version_number=1,
            policy_snapshot_hash=policy_hash,
            prompt_template_hash=prompt_hash,
            allowed_tools=tuple(initial_allowed_tools),
            governance_rules=rules,
            created_at=datetime.now(UTC).isoformat(),
        )
        self._snapshots.append(initial_snapshot)
        self._active_snapshot = initial_snapshot

        self._task_bindings: dict[str, TaskPolicyBinding] = {}
        self._emergency_directives: list[EmergencyHotKillDirective] = []

    @property
    def active_snapshot(self) -> ExecutionPolicySnapshot:
        """Currently active snapshot used for newly initiated tasks."""
        return self._active_snapshot

    @property
    def total_snapshots(self) -> int:
        """Total number of historical policy versions."""
        return len(self._snapshots)

    def bind_task_policy(self, task_id: str) -> ExecutionPolicySnapshot:
        """Pin the current active policy snapshot to a running task."""
        if task_id in self._task_bindings:
            return self._task_bindings[task_id].snapshot

        binding = TaskPolicyBinding(
            task_id=task_id,
            snapshot=self._active_snapshot,
            bound_at=datetime.now(UTC).isoformat(),
        )
        self._task_bindings[task_id] = binding
        return binding.snapshot

    def get_task_policy(self, task_id: str) -> ExecutionPolicySnapshot | None:
        """Retrieve the pinned policy snapshot for an in-flight task."""
        binding = self._task_bindings.get(task_id)
        return binding.snapshot if binding is not None else None

    def apply_soft_update(
        self,
        new_prompt_template: str,
        new_allowed_tools: Sequence[str],
        new_governance_rules: Mapping[str, JsonScalar] | None = None,
    ) -> ExecutionPolicySnapshot:
        """Apply Track A Soft Update: new policy takes effect ONLY for subsequent new tasks."""
        rules = dict(new_governance_rules) if new_governance_rules is not None else {}
        prompt_hash = hashlib.sha256(new_prompt_template.encode("utf-8")).hexdigest()
        next_version = len(self._snapshots) + 1
        policy_hash = compute_policy_hash(next_version, prompt_hash, new_allowed_tools, rules)

        new_snapshot = ExecutionPolicySnapshot(
            snapshot_id=f"snap-{uuid.uuid4().hex[:10]}",
            version_number=next_version,
            policy_snapshot_hash=policy_hash,
            prompt_template_hash=prompt_hash,
            allowed_tools=tuple(new_allowed_tools),
            governance_rules=rules,
            created_at=datetime.now(UTC).isoformat(),
        )

        self._snapshots.append(new_snapshot)
        self._active_snapshot = new_snapshot
        return new_snapshot

    def apply_emergency_hot_kill(
        self,
        revoked_tools: Sequence[str],
        reason: str,
    ) -> EmergencyHotKillDirective:
        """Apply Track B Emergency Hot Kill: immediately bans tools across all in-flight tasks."""
        directive = EmergencyHotKillDirective(
            directive_id=f"hotkill-{uuid.uuid4().hex[:10]}",
            revoked_tools=tuple(revoked_tools),
            reason=reason,
            issued_at=datetime.now(UTC).isoformat(),
            is_active=True,
        )
        self._emergency_directives.append(directive)
        return directive

    def revoke_emergency_hot_kill(self, directive_id: str) -> bool:
        """Revoke an active emergency hot-kill directive."""
        for idx, d in enumerate(self._emergency_directives):
            if d.directive_id == directive_id and d.is_active:
                updated = EmergencyHotKillDirective(
                    directive_id=d.directive_id,
                    revoked_tools=d.revoked_tools,
                    reason=d.reason,
                    issued_at=d.issued_at,
                    is_active=False,
                )
                self._emergency_directives[idx] = updated
                return True
        return False

    def assert_tool_execution_allowed(self, task_id: str, tool_name: str) -> None:
        """Assert that tool execution is permitted under task's pinned policy & hot-kills."""
        # 1. Emergency Hot Kill Check (immediate global effect)
        for directive in self._emergency_directives:
            if directive.is_active and tool_name in directive.revoked_tools:
                raise EmergencyHotKillBlockedError(
                    f"Tool '{tool_name}' blocked by active emergency hot-kill "
                    f"[{directive.directive_id}]: {directive.reason}"
                )

        # 2. Pinned Policy Snapshot Check
        snapshot = self.get_task_policy(task_id)
        if snapshot is None:
            snapshot = self.bind_task_policy(task_id)

        if tool_name not in snapshot.allowed_tools:
            raise PolicyDriftViolationError(
                f"Tool '{tool_name}' is not permitted by pinned policy snapshot "
                f"(v{snapshot.version_number}, hash {snapshot.policy_snapshot_hash[:8]})"
            )
