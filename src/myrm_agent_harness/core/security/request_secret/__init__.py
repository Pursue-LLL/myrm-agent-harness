"""
[POS] src/myrm_agent_harness/core/security/request_secret/__init__.py
Request-Secret Masked Credential Card Suite.
Exports domain types, session manager, sanitizer, and facade.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from .card_manager import SecretCardSessionManager
from .facade import RequestSecretMaskedCredentialCardFacade
from .sanitizer import IncompleteCredentialError, SecretPayloadSanitizer
from .types import (
    MaskedCredentialRef,
    SanitizedSecretResult,
    SecretCardSession,
    SecretInputSubmission,
    SecretRequestIntent,
    SecretRequestStatus,
)

__all__ = [
    "IncompleteCredentialError",
    "MaskedCredentialRef",
    "RequestSecretMaskedCredentialCardFacade",
    "SanitizedSecretResult",
    "SecretCardSession",
    "SecretCardSessionManager",
    "SecretInputSubmission",
    "SecretPayloadSanitizer",
    "SecretRequestIntent",
    "SecretRequestStatus",
]
