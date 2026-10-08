"""Two-Stage Staging Approval Gate enforcing out-of-chat host signed token approvals.

[INPUT]
- StagedChangeDraft, HostApprovalToken
- session_id, target_entity_id, mutation_type, diff_payload

[OUTPUT]
- TwoStageApprovalGate: stages high-impact mutations and validates host platform authorization tokens.
- StagedChangeNotApprovedError: raised when an unapproved or forged staged change is applied.

[POS]
Harness core security module inspired by Anthropic Commerce Agents (APPROVAL_GATE & Out-of-Chat Interlock).
"""

from __future__ import annotations

import hashlib
import hmac
import threading
import time
import uuid

from myrm_agent_harness.core.security.provenance_gate.types import (
    HostApprovalToken,
    StagedChangeDraft,
    StagedChangeNotApprovedError,
    StagedChangeStatus,
)


def _compute_token_signature(staged_id: str, operator_id: str, valid_until: float, secret_key: str) -> str:
    """Compute HMAC-SHA256 signature for host approval token."""
    message = f"{staged_id}:{operator_id}:{valid_until:.2f}".encode()
    return hmac.new(secret_key.encode("utf-8"), message, hashlib.sha256).hexdigest()


class TwoStageApprovalGate:
    """Enforces two-stage mutation staging and explicit host signed token authorization."""

    def __init__(self, secret_key: str = "myrm_enclave_host_secret_default") -> None:
        self._secret_key = secret_key
        self._staged_changes: dict[str, StagedChangeDraft] = {}
        self._lock = threading.Lock()

    def stage_change(
        self,
        session_id: str,
        target_entity_id: str,
        mutation_type: str,
        diff_payload: dict[str, str | int | float | bool],
        ttl_seconds: float = 300.0,
    ) -> StagedChangeDraft:
        """Stage a proposed high-impact mutation draft into staging."""
        staged_id = f"stg_{uuid.uuid4().hex[:10]}"
        now = time.time()
        draft = StagedChangeDraft(
            staged_id=staged_id,
            session_id=session_id,
            target_entity_id=target_entity_id,
            mutation_type=mutation_type,
            diff_payload=diff_payload,
            status=StagedChangeStatus.STAGED,
            host_token_id=None,
            created_at=now,
            expires_at=now + ttl_seconds,
        )
        with self._lock:
            self._staged_changes[staged_id] = draft
        return draft

    def issue_host_approval_token(
        self,
        staged_id: str,
        operator_id: str,
        ttl_seconds: float = 60.0,
    ) -> HostApprovalToken:
        """Issue an authentic host platform signed token for a staged change."""
        with self._lock:
            draft = self._staged_changes.get(staged_id)
            if not draft:
                raise StagedChangeNotApprovedError(staged_id, "Staged change not found")
            if draft.status != StagedChangeStatus.STAGED:
                raise StagedChangeNotApprovedError(
                    staged_id, f"Cannot issue approval token for change in state '{draft.status}'"
                )

        now = time.time()
        valid_until = now + ttl_seconds
        sig = _compute_token_signature(staged_id, operator_id, valid_until, self._secret_key)
        token_id = f"tok_{uuid.uuid4().hex[:10]}"

        return HostApprovalToken(
            token_id=token_id,
            staged_id=staged_id,
            operator_id=operator_id,
            signature=sig,
            issued_at=now,
            valid_until=valid_until,
        )

    def apply_staged_change(
        self,
        staged_id: str,
        token: HostApprovalToken,
    ) -> StagedChangeDraft:
        """Verify host token cryptographic signature and apply the staged mutation."""
        now = time.time()

        # 1. Verify token attributes
        if token.staged_id != staged_id:
            raise StagedChangeNotApprovedError(
                staged_id, f"Token staged_id mismatch: got '{token.staged_id}', expected '{staged_id}'"
            )
        if now > token.valid_until:
            raise StagedChangeNotApprovedError(staged_id, "Host approval token has expired")

        # 2. Verify HMAC signature
        expected_sig = _compute_token_signature(
            staged_id, token.operator_id, token.valid_until, self._secret_key
        )
        if not hmac.compare_digest(token.signature, expected_sig):
            raise StagedChangeNotApprovedError(staged_id, "Invalid or forged host token signature")

        with self._lock:
            draft = self._staged_changes.get(staged_id)
            if not draft:
                raise StagedChangeNotApprovedError(staged_id, "Staged change not found")
            if draft.status != StagedChangeStatus.STAGED:
                raise StagedChangeNotApprovedError(
                    staged_id, f"Change cannot be applied from status '{draft.status}'"
                )
            if now > draft.expires_at:
                expired = StagedChangeDraft(
                    staged_id=draft.staged_id,
                    session_id=draft.session_id,
                    target_entity_id=draft.target_entity_id,
                    mutation_type=draft.mutation_type,
                    diff_payload=draft.diff_payload,
                    status=StagedChangeStatus.EXPIRED,
                    host_token_id=None,
                    created_at=draft.created_at,
                    expires_at=draft.expires_at,
                )
                self._staged_changes[staged_id] = expired
                raise StagedChangeNotApprovedError(staged_id, "Staged change draft has expired")

            applied = StagedChangeDraft(
                staged_id=draft.staged_id,
                session_id=draft.session_id,
                target_entity_id=draft.target_entity_id,
                mutation_type=draft.mutation_type,
                diff_payload=draft.diff_payload,
                status=StagedChangeStatus.APPLIED,
                host_token_id=token.token_id,
                created_at=draft.created_at,
                expires_at=draft.expires_at,
            )
            self._staged_changes[staged_id] = applied
            return applied

    def reject_staged_change(self, staged_id: str) -> StagedChangeDraft:
        """Reject and cancel a staged mutation draft."""
        with self._lock:
            draft = self._staged_changes.get(staged_id)
            if not draft:
                raise StagedChangeNotApprovedError(staged_id, "Staged change not found")
            if draft.status != StagedChangeStatus.STAGED:
                raise StagedChangeNotApprovedError(
                    staged_id, f"Cannot reject change in status '{draft.status}'"
                )

            rejected = StagedChangeDraft(
                staged_id=draft.staged_id,
                session_id=draft.session_id,
                target_entity_id=draft.target_entity_id,
                mutation_type=draft.mutation_type,
                diff_payload=draft.diff_payload,
                status=StagedChangeStatus.REJECTED,
                host_token_id=None,
                created_at=draft.created_at,
                expires_at=draft.expires_at,
            )
            self._staged_changes[staged_id] = rejected
            return rejected

    def get_staged_change(self, staged_id: str) -> StagedChangeDraft | None:
        """Retrieve staged draft by ID."""
        with self._lock:
            return self._staged_changes.get(staged_id)

    def list_staged_changes(self, session_id: str | None = None) -> list[StagedChangeDraft]:
        """List active staged changes, optionally filtered by session ID."""
        with self._lock:
            changes = list(self._staged_changes.values())
        if session_id:
            changes = [c for c in changes if c.session_id == session_id]
        return changes
