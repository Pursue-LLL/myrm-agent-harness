"""Session state delta engine and explicit invalidation compiler.

[INPUT]
Active session variables (sandbox mode, privileges, CWD, environment keys) and turn lifecycles.

[OUTPUT]
Zero-token no-op when unchanged, tail-appended structured updates, and explicit invalidation notices.

[POS]
Core runtime state engine benchmarked against DeepSeek Harness 5-step prompt cache protection.
"""

import threading
import uuid
from collections.abc import Mapping

from myrm_agent_harness.runtime.context.session_state_delta_types import (
    SessionStateDeltaPackage,
    SessionStateSnapshot,
    StateDeltaAuditRecord,
    StateDeltaItem,
    StateMutationKind,
)


class SessionStateDeltaEngine:
    """Manages conversational session variables with strict diffing and explicit invalidation."""

    def __init__(self, initial_variables: Mapping[str, str] | None = None) -> None:
        self._lock = threading.RLock()
        self._revision = 1
        self._active_variables: dict[str, str] = (
            dict(initial_variables) if initial_variables else {}
        )
        self._invalidation_reasons: dict[str, str] = {}
        # None represents that no prior snapshot has been synced to the model yet
        self._synced_snapshot: SessionStateSnapshot | None = None
        self._audit_log: list[StateDeltaAuditRecord] = []

    def set_variable(self, key: str, value: str) -> None:
        """Set or update a session state variable."""
        with self._lock:
            clean_key = key.strip()
            if self._active_variables.get(clean_key) != value:
                self._active_variables[clean_key] = value
                self._invalidation_reasons.pop(clean_key, None)
                self._revision += 1

    def update_variables(self, variables: Mapping[str, str]) -> None:
        """Bulk update session state variables."""
        with self._lock:
            for k, v in variables.items():
                self.set_variable(k, v)

    def remove_variable(self, key: str, reason: str | None = None) -> bool:
        """Explicitly invalidate and remove a session state variable."""
        with self._lock:
            clean_key = key.strip()
            if clean_key in self._active_variables:
                del self._active_variables[clean_key]
                if reason:
                    self._invalidation_reasons[clean_key] = reason
                self._revision += 1
                return True
            return False

    def clear_variables(self, reason: str | None = "Cleared all session state variables") -> None:
        """Invalidate and remove all active session state variables."""
        with self._lock:
            for k in list(self._active_variables.keys()):
                self.remove_variable(k, reason=reason)

    def compute_turn_delta(self, turn_index: int = 0) -> SessionStateDeltaPackage:
        """Compute delta between current state and last synced snapshot, preserving prefix cache."""
        with self._lock:
            from_rev = self._synced_snapshot.revision if self._synced_snapshot else 0
            to_rev = self._revision

            old_vars = self._synced_snapshot.variables if self._synced_snapshot else {}
            curr_vars = dict(self._active_variables)

            mutations: list[StateDeltaItem] = []

            # 1. Detect additions and modifications
            for k, v in curr_vars.items():
                if k not in old_vars:
                    mutations.append(
                        StateDeltaItem(
                            key=k,
                            mutation_kind=StateMutationKind.ADDED,
                            old_value=None,
                            new_value=v,
                        )
                    )
                elif old_vars[k] != v:
                    mutations.append(
                        StateDeltaItem(
                            key=k,
                            mutation_kind=StateMutationKind.UPDATED,
                            old_value=old_vars[k],
                            new_value=v,
                        )
                    )

            # 2. Detect invalidations
            invalidated_keys: list[str] = []
            for k in old_vars:
                if k not in curr_vars:
                    reason = self._invalidation_reasons.pop(k, "Variable revoked or cleared")
                    mutations.append(
                        StateDeltaItem(
                            key=k,
                            mutation_kind=StateMutationKind.INVALIDATED,
                            old_value=old_vars[k],
                            new_value=None,
                            invalidation_reason=reason,
                        )
                    )
                    invalidated_keys.append(k)

            # If no changes whatsoever, 0 token injection!
            if not mutations:
                return SessionStateDeltaPackage(
                    from_revision=from_rev,
                    to_revision=to_rev,
                    has_mutations=False,
                    mutations=(),
                    formatted_tail_payload="",
                    token_delta_estimate=0,
                )

            # Format XML-style delta payload strictly for tail append
            payload_lines: list[str] = []
            for m in mutations:
                if m.mutation_kind in (StateMutationKind.ADDED, StateMutationKind.UPDATED):
                    payload_lines.append(
                        f'<session_state_update key="{m.key}">{m.new_value}</session_state_update>'
                    )
                elif m.mutation_kind == StateMutationKind.INVALIDATED:
                    payload_lines.append(
                        f'<session_state_invalidated key="{m.key}" reason="{m.invalidation_reason}" />'
                    )

            formatted_payload = "\n".join(payload_lines)
            token_estimate = max(1, len(formatted_payload) // 4)

            # Update synced snapshot
            new_snapshot = SessionStateSnapshot(
                revision=to_rev,
                variables=curr_vars,
            )
            self._synced_snapshot = new_snapshot

            # Record audit
            audit_entry = StateDeltaAuditRecord(
                audit_id=f"audit-{uuid.uuid4().hex[:8]}",
                turn_index=turn_index,
                from_revision=from_rev,
                to_revision=to_rev,
                mutations_count=len(mutations),
                invalidated_keys=tuple(invalidated_keys),
            )
            self._audit_log.append(audit_entry)

            return SessionStateDeltaPackage(
                from_revision=from_rev,
                to_revision=to_rev,
                has_mutations=True,
                mutations=tuple(mutations),
                formatted_tail_payload=formatted_payload,
                token_delta_estimate=token_estimate,
            )

    @classmethod
    def attach_delta_to_tail(
        cls,
        prompt_content: str,
        delta: SessionStateDeltaPackage,
    ) -> str:
        """Safely attach delta updates strictly at the tail of user message, preserving cache."""
        if not delta.has_mutations or not delta.formatted_tail_payload:
            return prompt_content

        trimmed = prompt_content.rstrip()
        return f"{trimmed}\n\n<!-- Runtime Session State Delta -->\n{delta.formatted_tail_payload}"

    def get_active_snapshot(self) -> SessionStateSnapshot:
        """Retrieve current active snapshot."""
        with self._lock:
            return SessionStateSnapshot(
                revision=self._revision,
                variables=dict(self._active_variables),
            )

    def get_audit_history(self) -> list[StateDeltaAuditRecord]:
        """Retrieve audit history of state deltas."""
        with self._lock:
            return list(self._audit_log)
