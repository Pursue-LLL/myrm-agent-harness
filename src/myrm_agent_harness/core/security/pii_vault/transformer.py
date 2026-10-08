"""Bidirectional PII pseudonymization and reverse reconstruction transformer.

[INPUT]
- Text string, session_id, LocalPiiMappingVault

[OUTPUT]
- SanitizationResult (outbound anonymized text)
- DesanitizationResult (inbound restored original text)

[POS]
Harness core security module for client-side privacy preservation (Transparent Pseudonymization Transformer).
"""

from __future__ import annotations

import time

from myrm_agent_harness.core.security.pii_vault.detector import PiiEntityDetector
from myrm_agent_harness.core.security.pii_vault.types import (
    DesanitizationResult,
    PiiEntityMatch,
    SanitizationResult,
)
from myrm_agent_harness.core.security.pii_vault.vault import LocalPiiMappingVault


class PiiTransformer:
    """Performs transparent outward pseudonymization and inward desanitization."""

    @classmethod
    def pseudonymize(
        cls,
        text: str,
        session_id: str,
        vault: LocalPiiMappingVault,
    ) -> SanitizationResult:
        """Scan text, replace detected PII with session-consistent placeholders, and save to vault."""
        if not text:
            return SanitizationResult(
                sanitized_text="",
                placeholders_count=0,
                entities_detected=(),
                session_id=session_id,
                sanitized_at=time.time(),
            )

        matches = PiiEntityDetector.detect_entities(text)
        if not matches:
            return SanitizationResult(
                sanitized_text=text,
                placeholders_count=0,
                entities_detected=(),
                session_id=session_id,
                sanitized_at=time.time(),
            )

        # Build consistent replacements (reusing existing placeholder for identical values)
        resolved_matches: list[PiiEntityMatch] = []
        for m in matches:
            existing_placeholder = vault.get_placeholder(session_id, m.raw_value)
            if existing_placeholder:
                placeholder = existing_placeholder
            else:
                placeholder = m.placeholder
                vault.store_mapping(session_id, placeholder, m.raw_value)

            resolved_matches.append(
                PiiEntityMatch(
                    entity_type=m.entity_type,
                    raw_value=m.raw_value,
                    placeholder=placeholder,
                    start_idx=m.start_idx,
                    end_idx=m.end_idx,
                )
            )

        # Replace in reverse order so character indices remain valid
        sanitized_chars = list(text)
        sorted_for_replacement = sorted(resolved_matches, key=lambda x: x.start_idx, reverse=True)
        for rm in sorted_for_replacement:
            sanitized_chars[rm.start_idx : rm.end_idx] = list(rm.placeholder)

        sanitized_text = "".join(sanitized_chars)
        return SanitizationResult(
            sanitized_text=sanitized_text,
            placeholders_count=len(resolved_matches),
            entities_detected=tuple(resolved_matches),
            session_id=session_id,
            sanitized_at=time.time(),
        )

    @classmethod
    def desanitize(
        cls,
        text: str,
        session_id: str,
        vault: LocalPiiMappingVault,
    ) -> DesanitizationResult:
        """Reverse replace placeholders back to original PII strings from the local vault."""
        if not text:
            return DesanitizationResult(
                restored_text="",
                restored_count=0,
                placeholders_found=(),
                session_id=session_id,
                restored_at=time.time(),
            )

        mapping = vault.list_mappings(session_id)
        if not mapping:
            return DesanitizationResult(
                restored_text=text,
                restored_count=0,
                placeholders_found=(),
                session_id=session_id,
                restored_at=time.time(),
            )

        restored_text = text
        found_placeholders: list[str] = []
        total_restored = 0

        # Replace each placeholder registered in the session
        for placeholder, real_value in mapping.items():
            if placeholder in restored_text:
                count = restored_text.count(placeholder)
                restored_text = restored_text.replace(placeholder, real_value)
                found_placeholders.append(placeholder)
                total_restored += count

        return DesanitizationResult(
            restored_text=restored_text,
            restored_count=total_restored,
            placeholders_found=tuple(found_placeholders),
            session_id=session_id,
            restored_at=time.time(),
        )
