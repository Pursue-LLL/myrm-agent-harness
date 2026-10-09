"""Master facade suite for corrupt session degradation and zero-freeze auto-healing.

[INPUT]
- healing_types: All contracts, outcomes, archives, and configuration models.
- corrupt_record_sandbox: CorruptRecordSandbox.
- partial_transcript_salvager: PartialTranscriptSalvager.
- fresh_session_auto_healer: FreshSessionAutoHealer.

[OUTPUT]
- CorruptSessionStorageGracefulDegradationAndAutoHealingSuite: Master facade
  orchestrating safe session restoration, salvage, quarantine, and fresh fallback derivation.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.corrupt_session_healing
- Module: corrupt_session_healing_suite.py
"""

from typing import Optional, Sequence
from myrm_agent_harness.agent.context_management.corrupt_session_healing.corrupt_record_sandbox import (
    CorruptRecordSandbox,
)
from myrm_agent_harness.agent.context_management.corrupt_session_healing.fresh_session_auto_healer import (
    FreshSessionAutoHealer,
)
from myrm_agent_harness.agent.context_management.corrupt_session_healing.healing_types import (
    CorruptRecordArchive,
    HealingSuiteConfig,
    RestorationOutcome,
    RestorationStatus,
    SalvagedMessageItem,
)
from myrm_agent_harness.agent.context_management.corrupt_session_healing.partial_transcript_salvager import (
    PartialTranscriptSalvager,
)


class CorruptSessionStorageGracefulDegradationAndAutoHealingSuite:
    """Master facade providing seamless degradation and self-healing for corrupted session storage."""

    def __init__(self, config: Optional[HealingSuiteConfig] = None) -> None:
        self._config = config or HealingSuiteConfig()
        self._sandbox = CorruptRecordSandbox(self._config)
        self._salvager = PartialTranscriptSalvager(self._config)
        self._healer = FreshSessionAutoHealer(self._config)

    @property
    def sandbox(self) -> CorruptRecordSandbox:
        """Access the corruption quarantine sandbox."""
        return self._sandbox

    @property
    def salvager(self) -> PartialTranscriptSalvager:
        """Access the partial transcript salvager."""
        return self._salvager

    @property
    def healer(self) -> FreshSessionAutoHealer:
        """Access the fresh session auto-healer."""
        return self._healer

    def restore_session_safe(
        self,
        session_id: str,
        raw_payload: str,
        deserializer_error: Optional[str] = None,
    ) -> RestorationOutcome:
        """Safely restores a session, quarantining corrupt data and activating fresh fallback if needed.

        Args:
            session_id: Target session identifier to restore.
            raw_payload: Stored string representation (JSON, JSONL, or binary transcript).
            deserializer_error: Optional explicit error reported by storage parser.

        Returns:
            RestorationOutcome specifying clean restoration, partial salvage, or fresh healing.
        """
        # If no error reported, attempt clean salvage
        if not deserializer_error:
            clean_messages = self._salvager._try_parse_full_json(raw_payload)
            if clean_messages is not None:
                return RestorationOutcome(
                    original_session_id=session_id,
                    active_session_id=session_id,
                    status=RestorationStatus.RESTORED_CLEAN,
                    salvaged_messages=clean_messages,
                    is_fresh_session=False,
                    diagnostic_message="Session restored cleanly without errors.",
                )

        # Failure occurred: run forensic salvage and quarantine
        diag_msg = deserializer_error or "Payload failed structured JSON parsing."
        salvaged = self._salvager.salvage(raw_payload) if self._config.attempt_partial_salvage else tuple()

        # 1. Quarantine corrupted payload
        self._sandbox.quarantine_payload(
            session_id=session_id,
            raw_payload=raw_payload,
            error_diagnostic=diag_msg,
            salvaged_count=len(salvaged),
        )

        # 2. Derive zero-freeze fresh healed session
        if self._config.auto_activate_fresh_session:
            return self._healer.derive_healed_session(
                corrupted_session_id=session_id,
                salvaged_messages=salvaged,
                diagnostic_reason=diag_msg,
            )

        return RestorationOutcome(
            original_session_id=session_id,
            active_session_id=session_id,
            status=RestorationStatus.UNRECOVERABLE,
            salvaged_messages=salvaged,
            is_fresh_session=False,
            diagnostic_message=f"Session corrupted and fresh activation disabled: {diag_msg}",
        )

    def get_quarantine_archive(self, session_id: str) -> Optional[CorruptRecordArchive]:
        """Retrieves quarantine archive record for a corrupted session."""
        return self._sandbox.get_archive(session_id)

    def list_quarantined_archives(self) -> Sequence[CorruptRecordArchive]:
        """Lists all quarantined session corruption records."""
        return self._sandbox.list_archives()

    def render_restoration_intro(self, outcome: RestorationOutcome) -> str:
        """Renders an introductory system guidance block for a healed session."""
        return self._healer.render_healed_context_intro(outcome)
