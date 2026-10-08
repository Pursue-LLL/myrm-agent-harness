"""
[POS] src/myrm_agent_harness/core/security/request_secret/facade.py
[INPUT] typing, types, card_manager, sanitizer
[OUTPUT] RequestSecretMaskedCredentialCardFacade
Unified facade for request_secret cards, masked backfills, and transcript-safe secret injection.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging

from .card_manager import SecretCardSessionManager
from .sanitizer import SecretPayloadSanitizer
from .types import (
    MaskedCredentialRef,
    SanitizedSecretResult,
    SecretCardSession,
    SecretInputSubmission,
    SecretRequestIntent,
)

logger = logging.getLogger(__name__)


class RequestSecretMaskedCredentialCardFacade:
    """Unified entrypoint for agent request_secret cards and zero-transcript credential handling."""

    def __init__(
        self,
        manager: SecretCardSessionManager | None = None,
        sanitizer: SecretPayloadSanitizer | None = None,
    ) -> None:
        self._sanitizer = sanitizer or SecretPayloadSanitizer()
        self._manager = manager or SecretCardSessionManager(self._sanitizer)

    @property
    def manager(self) -> SecretCardSessionManager:
        """Underlying card session manager."""
        return self._manager

    @property
    def sanitizer(self) -> SecretPayloadSanitizer:
        """Underlying payload sanitizer."""
        return self._sanitizer

    def create_secret_request_card(
        self,
        agent_id: str,
        task_id: str,
        intent: SecretRequestIntent,
    ) -> SecretCardSession:
        """Create an interactive secret request card session for the user."""
        return self._manager.create_card_session(
            agent_id=agent_id,
            task_id=task_id,
            intent=intent,
        )

    def fulfill_secret_request(
        self,
        card_id: str,
        submission: SecretInputSubmission,
    ) -> SanitizedSecretResult:
        """Fulfill a secret request card using raw input or an existing masked credential."""
        return self._manager.fulfill_card(
            card_id=card_id,
            submission=submission,
        )

    def reject_secret_request(
        self,
        card_id: str,
        reason: str = "User declined to provide secret",
    ) -> SecretCardSession:
        """Reject and invalidate an active secret request card."""
        return self._manager.reject_card(card_id=card_id, reason=reason)

    def get_card_session(self, card_id: str) -> SecretCardSession | None:
        """Retrieve details of a secret card session."""
        return self._manager.get_session(card_id)

    def register_saved_credential(
        self,
        target_system: str,
        raw_secret: str,
        credential_id: str | None = None,
    ) -> MaskedCredentialRef:
        """Store a pre-configured credential and return its safe masked reference."""
        return self._manager.register_saved_credential(
            target_system=target_system,
            raw_secret=raw_secret,
            credential_id=credential_id,
        )

    def list_saved_credentials(
        self, target_system: str | None = None
    ) -> list[MaskedCredentialRef]:
        """List safe masked credential references available for backfill."""
        return self._manager.list_saved_credentials(target_system=target_system)
