"""Engine for session anti-poisoning and 1-click antidote.

Protects sessions against accidental or autonomous feature flag poisoning,
quarantines ephemeral turn mutations, monitors config drift, and provides
atomic rollback to clean genesis baseline while preserving conversation history.
"""

import copy
import logging
from typing import Optional

from .session_antidote_types import (
    AntidoteReceipt,
    ConfigDriftDetail,
    ConfigMutationProposal,
    FlagScope,
    GenesisConfigSnapshot,
    PoisonDiagnosisReport,
    PoisonSeverity,
    SessionAntidoteConfig,
)

logger = logging.getLogger(__name__)


class SessionAntiPoisoningEngine:
    """Core governor and antidote engine defending sessions against configuration poisoning."""

    def __init__(self, config: Optional[SessionAntidoteConfig] = None) -> None:
        self.config = config or SessionAntidoteConfig()
        self._genesis_registry: dict[str, GenesisConfigSnapshot] = {}
        self._persistent_flags: dict[str, dict[str, str]] = {}
        self._turn_ephemeral_flags: dict[str, dict[str, dict[str, str]]] = {}
        self._mutation_history: dict[str, list[ConfigMutationProposal]] = {}

    def register_genesis_config(
        self, session_id: str, base_flags: dict[str, str]
    ) -> GenesisConfigSnapshot:
        """Register the baseline genesis snapshot for a session."""
        snapshot = GenesisConfigSnapshot.create(session_id=session_id, base_flags=base_flags)
        self._genesis_registry[session_id] = snapshot
        self._persistent_flags[session_id] = dict(base_flags)
        self._turn_ephemeral_flags[session_id] = {}
        self._mutation_history[session_id] = []
        logger.info("Registered genesis snapshot for session %s (checksum=%s)", session_id, snapshot.checksum[:8])
        return snapshot

    def get_genesis_snapshot(self, session_id: str) -> Optional[GenesisConfigSnapshot]:
        """Retrieve registered genesis snapshot for a session."""
        return self._genesis_registry.get(session_id)

    def evaluate_mutation(
        self, session_id: str, proposal: ConfigMutationProposal
    ) -> tuple[bool, str, FlagScope]:
        """Evaluate a proposed flag mutation and assign security scope.

        Returns (accepted, reason, scope).
        """
        if session_id not in self._genesis_registry:
            return False, f"Session {session_id} not registered with genesis snapshot", FlagScope.REJECTED_BLOCKED

        self._mutation_history.setdefault(session_id, []).append(proposal)

        # Check for explicitly blocked dangerous flags
        dangerous_requested = set(proposal.requested_flags.keys()) & self.config.blocked_dangerous_flags
        if dangerous_requested and not proposal.explicit_user_approved:
            reason = f"Blocked dangerous flag mutation attempt: {dangerous_requested} without explicit approval"
            logger.warning(reason)
            return False, reason, FlagScope.REJECTED_BLOCKED

        # User approved mutations can become persistent
        if proposal.explicit_user_approved:
            for k, v in proposal.requested_flags.items():
                self._persistent_flags[session_id][k] = v
            return True, "User approved persistent mutation accepted", FlagScope.PERSISTENT_APPROVED

        # Autonomous model mutations are sandboxed to ephemeral turn scope only
        return True, "Sandboxed to ephemeral turn scope to prevent permanent poisoning", FlagScope.EPHEMERAL_TURN

    def apply_turn_ephemeral_flags(
        self, session_id: str, turn_id: str, flags: dict[str, str]
    ) -> dict[str, str]:
        """Apply temporary ephemeral flags bound strictly to a specific execution turn."""
        if session_id not in self._turn_ephemeral_flags:
            self._turn_ephemeral_flags[session_id] = {}

        self._turn_ephemeral_flags[session_id][turn_id] = dict(flags)
        return self.get_effective_flags(session_id=session_id, turn_id=turn_id)

    def finalize_turn_cleanup(self, session_id: str, turn_id: str) -> None:
        """Atomically discard ephemeral flags when a turn finishes to prevent drift escape."""
        if session_id in self._turn_ephemeral_flags and turn_id in self._turn_ephemeral_flags[session_id]:
            del self._turn_ephemeral_flags[session_id][turn_id]

    def get_effective_flags(
        self, session_id: str, turn_id: Optional[str] = None
    ) -> dict[str, str]:
        """Resolve current effective configuration combining persistent base and active turn sandbox."""
        base = copy.deepcopy(self._persistent_flags.get(session_id, {}))
        if turn_id and session_id in self._turn_ephemeral_flags:
            turn_flags = self._turn_ephemeral_flags[session_id].get(turn_id, {})
            base.update(turn_flags)
        return base

    def diagnose_session_health(
        self,
        session_id: str,
        current_runtime_flags: dict[str, str],
        error_cascade_count: int = 0,
    ) -> PoisonDiagnosisReport:
        """Inspect session configuration against genesis baseline to detect poisoning and drift."""
        snapshot = self._genesis_registry.get(session_id)
        if not snapshot:
            return PoisonDiagnosisReport(
                session_id=session_id,
                severity=PoisonSeverity.SUSPICIOUS,
                detected_drifts=[],
                offending_flags=[],
                recommendation="Session lacks genesis baseline snapshot. Register genesis immediately.",
            )

        detected_drifts: list[ConfigDriftDetail] = []
        offending_flags: list[str] = []

        # Check for dangerous flags that somehow entered runtime
        for k, v in current_runtime_flags.items():
            if k in self.config.blocked_dangerous_flags:
                offending_flags.append(k)
                detected_drifts.append(
                    ConfigDriftDetail(
                        flag_key=k,
                        baseline_value=snapshot.base_flags.get(k, "<absent>"),
                        observed_value=v,
                        drift_reason="Dangerous experimental flag active in runtime",
                    )
                )

        # Check for unauthorized drifted flags
        for k, v in current_runtime_flags.items():
            if k not in snapshot.base_flags and k not in self.config.allowed_autonomous_flags:
                if k not in offending_flags:
                    offending_flags.append(k)
                    detected_drifts.append(
                        ConfigDriftDetail(
                            flag_key=k,
                            baseline_value="<absent>",
                            observed_value=v,
                            drift_reason="Unregistered autonomous flag injection detected",
                        )
                    )

        # Determine severity based on offending flags and error cascades
        if offending_flags and any(f in self.config.blocked_dangerous_flags for f in offending_flags):
            severity = PoisonSeverity.SEVERELY_POISONED
            rec = "CRITICAL: Dangerous flags active. Apply 1-Click Antidote immediately to restore genesis."
        elif len(detected_drifts) >= self.config.max_drift_tolerance or error_cascade_count >= 2:
            severity = PoisonSeverity.POTENTIALLY_POISONED
            rec = "Significant configuration drift with error cascades. Antidote rollback strongly recommended."
        elif detected_drifts:
            severity = PoisonSeverity.SUSPICIOUS
            rec = "Minor drift detected; monitor closely or reset to genesis baseline."
        else:
            severity = PoisonSeverity.CLEAN
            rec = "Session configuration is clean and aligned with genesis baseline."

        return PoisonDiagnosisReport(
            session_id=session_id,
            severity=severity,
            detected_drifts=detected_drifts,
            offending_flags=offending_flags,
            recommendation=rec,
        )

    def apply_one_click_antidote(
        self, session_id: str, preserved_turns_count: int
    ) -> AntidoteReceipt:
        """Execute 1-Click Antidote: purge all drifted flags, restore genesis baseline, preserve history."""
        snapshot = self._genesis_registry.get(session_id)
        if not snapshot:
            raise KeyError(f"Cannot apply antidote: Session {session_id} has no registered genesis baseline")

        current_persistent = self._persistent_flags.get(session_id, {})
        purged: list[str] = []

        # Find flags not present in genesis baseline or modified
        for k in list(current_persistent.keys()):
            if k not in snapshot.base_flags or current_persistent[k] != snapshot.base_flags[k]:
                purged.append(k)

        # Atomically restore persistent flags to exact genesis baseline
        self._persistent_flags[session_id] = dict(snapshot.base_flags)

        # Wipe any hanging ephemeral flags across turns
        if session_id in self._turn_ephemeral_flags:
            self._turn_ephemeral_flags[session_id].clear()

        receipt = AntidoteReceipt(
            session_id=session_id,
            purged_flags=purged,
            restored_flags_count=len(snapshot.base_flags),
            preserved_turns_count=preserved_turns_count,
            restored_to_checksum=snapshot.checksum,
        )
        logger.info(
            "1-Click Antidote applied to session %s: %d flags purged, restored checksum %s, %d turns preserved",
            session_id,
            len(purged),
            snapshot.checksum[:8],
            preserved_turns_count,
        )
        return receipt
