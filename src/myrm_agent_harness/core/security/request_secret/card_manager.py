"""
[POS] src/myrm_agent_harness/core/security/request_secret/card_manager.py
[INPUT] time, uuid, typing, types, sanitizer
[OUTPUT] SecretCardSessionManager
Lifecycle manager for secret request card sessions, masked credential registry, and fulfillment verification.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
import time
import uuid

from .sanitizer import SecretPayloadSanitizer
from .types import (
    MaskedCredentialRef,
    SanitizedSecretResult,
    SecretCardSession,
    SecretInputSubmission,
    SecretRequestIntent,
    SecretRequestStatus,
)

logger = logging.getLogger(__name__)


class SecretCardSessionManager:
    """Manages active secret card sessions and masked credential backfills."""

    def __init__(self, sanitizer: SecretPayloadSanitizer | None = None) -> None:
        self._sanitizer = sanitizer or SecretPayloadSanitizer()
        self._sessions: dict[str, SecretCardSession] = {}
        self._saved_credentials: dict[str, MaskedCredentialRef] = {}

    def create_card_session(
        self,
        agent_id: str,
        task_id: str,
        intent: SecretRequestIntent,
    ) -> SecretCardSession:
        """Create a new pending secret request card session."""
        card_id = f"card-sec-{uuid.uuid4().hex[:10]}"
        now = time.time()
        expires_at = now + intent.ttl_seconds

        session = SecretCardSession(
            card_id=card_id,
            agent_id=agent_id,
            task_id=task_id,
            intent=intent,
            status=SecretRequestStatus.PENDING,
            masked_ref=None,
            created_at=now,
            expires_at=expires_at,
        )
        self._sessions[card_id] = session
        logger.info(
            "Created secret request card %s for agent %s on target '%s'",
            card_id,
            agent_id,
            intent.target_system,
        )
        return session

    def register_saved_credential(
        self,
        target_system: str,
        raw_secret: str,
        credential_id: str | None = None,
    ) -> MaskedCredentialRef:
        """Register an existing saved credential in vault and return its safe masked reference."""
        cid = credential_id or f"cred-{target_system.lower()}-{uuid.uuid4().hex[:8]}"
        mask = self._sanitizer.generate_mask(raw_secret)
        ref = MaskedCredentialRef(
            credential_id=cid,
            target_system=target_system.lower(),
            mask_preview=mask,
            created_at=time.time(),
        )
        self._saved_credentials[cid] = ref
        logger.info(
            "Registered saved credential %s for system '%s' (mask=%s)",
            cid,
            target_system,
            mask,
        )
        return ref

    def list_saved_credentials(
        self, target_system: str | None = None
    ) -> list[MaskedCredentialRef]:
        """Return list of saved credential masked references, optionally filtered by target."""
        if target_system is None:
            return list(self._saved_credentials.values())
        tgt = target_system.lower()
        return [c for c in self._saved_credentials.values() if c.target_system == tgt]

    def get_session(self, card_id: str) -> SecretCardSession | None:
        """Retrieve session by ID, applying lazy expiration."""
        session = self._sessions.get(card_id)
        if session is None:
            return None

        # Check expiration
        if (
            session.status == SecretRequestStatus.PENDING
            and time.time() > session.expires_at
        ):
            session = SecretCardSession(
                card_id=session.card_id,
                agent_id=session.agent_id,
                task_id=session.task_id,
                intent=session.intent,
                status=SecretRequestStatus.EXPIRED,
                masked_ref=session.masked_ref,
                rejection_reason="Card session expired before user submission",
                created_at=session.created_at,
                expires_at=session.expires_at,
            )
            self._sessions[card_id] = session

        return session

    def fulfill_card(
        self,
        card_id: str,
        submission: SecretInputSubmission,
    ) -> SanitizedSecretResult:
        """Fulfill pending secret card session with user input or existing backfill."""
        session = self.get_session(card_id)
        if session is None:
            raise KeyError(f"Secret card session '{card_id}' not found")

        if session.status != SecretRequestStatus.PENDING:
            raise ValueError(
                f"Cannot fulfill card '{card_id}' in state '{session.status.value}'"
            )

        # Sanitize and validate submission
        mask_preview, is_backfill, _ = self._sanitizer.sanitize_submission(
            target_system=session.intent.target_system,
            submission=submission,
            saved_credentials=self._saved_credentials,
        )

        # Generate masked ref for session
        cred_id = (
            submission.selected_credential_id
            if is_backfill and submission.selected_credential_id
            else f"cred-temp-{uuid.uuid4().hex[:8]}"
        )
        masked_ref = MaskedCredentialRef(
            credential_id=cred_id,
            target_system=session.intent.target_system,
            mask_preview=mask_preview,
            created_at=time.time(),
        )

        fulfilled_session = SecretCardSession(
            card_id=session.card_id,
            agent_id=session.agent_id,
            task_id=session.task_id,
            intent=session.intent,
            status=SecretRequestStatus.FULFILLED,
            masked_ref=masked_ref,
            rejection_reason=None,
            created_at=session.created_at,
            expires_at=session.expires_at,
        )
        self._sessions[card_id] = fulfilled_session

        summary = (
            f"[Secret Authorized: target={session.intent.target_system}, "
            f"mask={mask_preview}, scope={session.intent.scope}, "
            f"backfill={is_backfill}, status=fulfilled]"
        )

        logger.info(
            "Fulfilled secret card %s for system '%s' (backfill=%s)",
            card_id,
            session.intent.target_system,
            is_backfill,
        )

        return SanitizedSecretResult(
            card_id=card_id,
            target_system=session.intent.target_system,
            mask_preview=mask_preview,
            is_backfill=is_backfill,
            stored_safely=True,
            transcript_safe_summary=summary,
        )

    def reject_card(
        self,
        card_id: str,
        reason: str = "User declined to provide secret",
    ) -> SecretCardSession:
        """Reject and invalidate an active secret card session."""
        session = self.get_session(card_id)
        if session is None:
            raise KeyError(f"Secret card session '{card_id}' not found")

        if session.status != SecretRequestStatus.PENDING:
            raise ValueError(
                f"Cannot reject card '{card_id}' in state '{session.status.value}'"
            )

        rejected_session = SecretCardSession(
            card_id=session.card_id,
            agent_id=session.agent_id,
            task_id=session.task_id,
            intent=session.intent,
            status=SecretRequestStatus.REJECTED,
            masked_ref=None,
            rejection_reason=reason,
            created_at=session.created_at,
            expires_at=session.expires_at,
        )
        self._sessions[card_id] = rejected_session
        logger.info("Rejected secret card %s: reason='%s'", card_id, reason)
        return rejected_session
