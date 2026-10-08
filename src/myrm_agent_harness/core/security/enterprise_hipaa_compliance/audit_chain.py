"""
[POS] src/myrm_agent_harness/core/security/enterprise_hipaa_compliance/audit_chain.py
[INPUT] hashlib, time, uuid, types
[OUTPUT] HipaaAuditChainEngine
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid

from .types import (
    ComplianceExportPackage,
    ComplianceStandard,
    HipaaAuditChainEntry,
)

logger = logging.getLogger(__name__)

GENESIS_HASH = "0000000000000000000000000000000000000000000000000000000000000000"


class HipaaAuditChainEngine:
    """Maintains an append-only, cryptographically linked SHA-256 audit chain for HIPAA compliance."""

    def __init__(self) -> None:
        self._entries: list[HipaaAuditChainEntry] = []

    @staticmethod
    def _calculate_hash(
        prev_hash: str,
        sequence_index: int,
        timestamp: float,
        event_type: str,
        agent_id: str,
        session_id: str,
        action_summary: str,
        phi_detected: bool,
    ) -> str:
        raw_payload = (
            f"{prev_hash}|{sequence_index}|{timestamp:.4f}|"
            f"{event_type}|{agent_id}|{session_id}|{action_summary}|{phi_detected}"
        )
        return hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()

    def append_event(
        self,
        event_type: str,
        agent_id: str,
        session_id: str,
        action_summary: str,
        phi_detected: bool = False,
        timestamp: float | None = None,
    ) -> HipaaAuditChainEntry:
        """Append an immutably hashed lifecycle event to the audit ledger."""
        now = time.time() if timestamp is None else timestamp
        seq_idx = len(self._entries)
        prev_hash = self._entries[-1].current_hash if self._entries else GENESIS_HASH

        curr_hash = self._calculate_hash(
            prev_hash=prev_hash,
            sequence_index=seq_idx,
            timestamp=now,
            event_type=event_type,
            agent_id=agent_id,
            session_id=session_id,
            action_summary=action_summary,
            phi_detected=phi_detected,
        )

        entry = HipaaAuditChainEntry(
            entry_id=f"audit-evt-{uuid.uuid4().hex[:12]}",
            sequence_index=seq_idx,
            event_type=event_type,
            agent_id=agent_id,
            session_id=session_id,
            timestamp=now,
            action_summary=action_summary,
            phi_detected=phi_detected,
            prev_hash=prev_hash,
            current_hash=curr_hash,
        )
        self._entries.append(entry)
        logger.debug("Appended HIPAA audit entry #%d (%s) hash: %s", seq_idx, event_type, curr_hash)
        return entry

    def verify_chain_integrity(self) -> tuple[bool, str]:
        """Verify sequential cryptographic link across all recorded entries."""
        if not self._entries:
            return True, "Audit chain is empty; 0 events recorded"

        expected_prev = GENESIS_HASH
        for idx, entry in enumerate(self._entries):
            if entry.sequence_index != idx:
                return False, f"Sequence index violation at position {idx}: expected {idx}, got {entry.sequence_index}"

            if entry.prev_hash != expected_prev:
                return False, f"Broken cryptographic chain at index {idx}: prev_hash mismatch"

            recomputed_hash = self._calculate_hash(
                prev_hash=entry.prev_hash,
                sequence_index=entry.sequence_index,
                timestamp=entry.timestamp,
                event_type=entry.event_type,
                agent_id=entry.agent_id,
                session_id=entry.session_id,
                action_summary=entry.action_summary,
                phi_detected=entry.phi_detected,
            )
            if recomputed_hash != entry.current_hash:
                return False, f"Data tampering detected at index {idx}: hash mismatch"

            expected_prev = entry.current_hash

        return True, f"Verified cryptographic integrity across {len(self._entries)} audit entries"

    def export_package(
        self,
        standard: ComplianceStandard = ComplianceStandard.HIPAA,
        current_time: float | None = None,
    ) -> ComplianceExportPackage:
        """Export verifiable compliance proof package with SHA-256 ledger digest."""
        now = time.time() if current_time is None else current_time
        chain_valid, _ = self.verify_chain_integrity()
        latest_hash = self._entries[-1].current_hash if self._entries else GENESIS_HASH

        summary_digest = hashlib.sha256(
            f"{standard.value}|{len(self._entries)}|{latest_hash}|{now:.4f}".encode()
        ).hexdigest()

        return ComplianceExportPackage(
            export_id=f"exp-{uuid.uuid4().hex[:12]}",
            compliance_standard=standard,
            generated_at=now,
            total_events=len(self._entries),
            chain_valid=chain_valid,
            ledger_entries=tuple(self._entries),
            summary_digest=summary_digest,
        )

    def get_entries(self) -> tuple[HipaaAuditChainEntry, ...]:
        """Fetch all recorded audit chain entries."""
        return tuple(self._entries)
