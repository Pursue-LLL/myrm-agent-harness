"""
[POS] src/myrm_agent_harness/core/security/request_secret/sanitizer.py
[INPUT] typing, types
[OUTPUT] IncompleteCredentialError, SecretPayloadSanitizer
Sanitizer for secret submissions enforcing field whitelisting, mask generation, and incomplete target rejection.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging

from .types import MaskedCredentialRef, SecretInputSubmission

logger = logging.getLogger(__name__)

# Allowed clean metadata keys
_ALLOWED_METADATA_KEYS: frozenset[str] = frozenset(
    {"account", "environment", "cluster", "workspace", "region", "label"}
)


class IncompleteCredentialError(Exception):
    """Exception raised when secret submission is incomplete or invalid."""


class SecretPayloadSanitizer:
    """Sanitizes user submissions, cleans planted fields, and generates masked fingerprints."""

    @staticmethod
    def generate_mask(raw: str) -> str:
        """Generate safe masked fingerprint preserving diagnostic prefix/suffix without exposing secret."""
        clean = raw.strip()
        if len(clean) <= 7:
            return "******"

        # Preserve diagnostic token family prefix if present (e.g. ghp_, sk-, whsec_)
        for sep in ("_", "-"):
            if sep in clean[:8]:
                idx = clean[:8].index(sep) + 1
                prefix = clean[:idx]
                suffix = clean[-4:]
                return f"{prefix}****{suffix}"

        prefix = clean[:3]
        suffix = clean[-4:]
        return f"{prefix}****{suffix}"

    @classmethod
    def sanitize_submission(
        cls,
        target_system: str,
        submission: SecretInputSubmission,
        saved_credentials: dict[str, MaskedCredentialRef],
    ) -> tuple[str, bool, dict[str, str]]:
        """Validate submission integrity, strip planted fields, and return (mask_preview, is_backfill, clean_meta).

        Raises:
            IncompleteCredentialError: if submission lacks both raw secret and valid credential reference.
        """
        if not target_system or not target_system.strip():
            raise IncompleteCredentialError("Target destination system must not be empty")

        # 1. Backfill resolution via existing saved credential
        if submission.selected_credential_id:
            cred_id = submission.selected_credential_id.strip()
            if cred_id not in saved_credentials:
                raise IncompleteCredentialError(
                    f"Selected credential '{cred_id}' not found in saved credential vault"
                )
            saved = saved_credentials[cred_id]
            if saved.target_system.lower() != target_system.lower():
                raise IncompleteCredentialError(
                    f"Selected credential target '{saved.target_system}' does not match requested '{target_system}'"
                )

            clean_meta = cls._clean_metadata(submission.extra_metadata)
            return saved.mask_preview, True, clean_meta

        # 2. Plaintext submission resolution
        if submission.raw_secret is not None:
            raw = submission.raw_secret.strip()
            if len(raw) < 4:
                raise IncompleteCredentialError("Provided secret length is too short to be a valid credential")

            mask = cls.generate_mask(raw)
            clean_meta = cls._clean_metadata(submission.extra_metadata)
            return mask, False, clean_meta

        # Neither raw secret nor backfill ID provided -> Incomplete target rejection
        raise IncompleteCredentialError(
            "Incomplete submission: must provide either raw_secret or valid selected_credential_id"
        )

    @staticmethod
    def _clean_metadata(extra_metadata: dict[str, str]) -> dict[str, str]:
        """Strip arbitrary or planted fields, keeping only verified whitelisted keys."""
        cleaned: dict[str, str] = {}
        for k, v in extra_metadata.items():
            k_norm = k.strip().lower()
            if k_norm in _ALLOWED_METADATA_KEYS:
                cleaned[k_norm] = str(v).strip()[:100]
            else:
                logger.debug("Stripped planted or unrecognized metadata key '%s'", k)
        return cleaned
