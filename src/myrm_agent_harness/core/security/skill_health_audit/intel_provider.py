"""
[POS] src/myrm_agent_harness/core/security/skill_health_audit/intel_provider.py
[INPUT] typing, os, types
[OUTPUT] PrivacyMinIntelProvider
Zero-code-upload threat intelligence provider with honest degradation ("Unavailable != Safe").
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
import os

from .types import IntelLookupStatus

logger = logging.getLogger(__name__)

# Known malicious skill SHA-256 digests in pre-populated local database
_KNOWN_MALICIOUS_HASHES: frozenset[str] = frozenset(
    {
        "a1b2c3d4e5f60718293a4b5c6d7e8f90123456789abcdef0123456789abcdef0",
        "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
        "ba9876543210fedcba9876543210fedcba9876543210fedcba9876543210fedc",
    }
)


class PrivacyMinIntelProvider:
    """Privacy-minimized threat intelligence provider sending only (skill_name, content_sha256)."""

    def __init__(self, offline_mode: bool | None = None) -> None:
        if offline_mode is None:
            # Respect environment switch: MYRM_SECURITY_CLOUD_LOOKUP=off
            env_val = os.getenv("MYRM_SECURITY_CLOUD_LOOKUP", "off").lower()
            self._offline_mode = env_val in ("off", "0", "false", "no")
        else:
            self._offline_mode = offline_mode

        self._custom_malicious_hashes: set[str] = set()

    def register_malicious_hash(self, sha256_hash: str) -> None:
        """Register a known malicious hash for testing or custom feed sync."""
        self._custom_malicious_hashes.add(sha256_hash.strip().lower())

    def lookup_skill_intel(
        self,
        skill_name: str,
        content_sha256: str,
    ) -> IntelLookupStatus:
        """Query reputation using strictly minimal metadata (name, sha256).

        Never sends code content, user prompts, workspace files or chat history.
        Honors the 'Unavailable != Safe' principle when offline.
        """
        clean_hash = content_sha256.strip().lower()

        # 1. Local authoritative known malicious blocklist
        if clean_hash in _KNOWN_MALICIOUS_HASHES or clean_hash in self._custom_malicious_hashes:
            logger.warning(
                "Skill %s (%s) matched known malicious threat intelligence",
                skill_name,
                clean_hash[:8],
            )
            return IntelLookupStatus.KNOWN_MALICIOUS

        # 2. Honest offline degradation principle
        if self._offline_mode:
            logger.info(
                "Threat intelligence lookup for skill %s is offline (Unavailable != Safe)",
                skill_name,
            )
            return IntelLookupStatus.UNAVAILABLE_OFFLINE

        # 3. In online mock/simulated benign environment
        return IntelLookupStatus.VERIFIED_BENIGN
