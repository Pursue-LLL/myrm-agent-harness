"""Master facade suite for terminal-missing silent end stream reconciliation.

[INPUT]
- silent_end_types: All contracts, enums, tickets, outcomes, and configuration models.
- stream_terminal_watchdog: StreamTerminalWatchdog.
- server_runtime_verifier: ServerRuntimeVerifier.

[OUTPUT]
- TerminalMissingSilentEndServerReconcileSuite: Master facade unifying
  SSE stream terminal monitoring and server-side run reservation reconciliation.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.silent_end_reconcile
- Module: silent_end_reconcile_suite.py
"""

from typing import Optional

from myrm_agent_harness.agent.context_management.silent_end_reconcile.server_runtime_verifier import (
    ServerRuntimeVerifier,
)
from myrm_agent_harness.agent.context_management.silent_end_reconcile.silent_end_types import (
    ReconcileOutcome,
    ServerRunReservation,
    SilentEndReconcileConfig,
    SilentEndTicket,
    StreamRunStatus,
)
from myrm_agent_harness.agent.context_management.silent_end_reconcile.stream_terminal_watchdog import (
    StreamTerminalWatchdog,
)


class TerminalMissingSilentEndServerReconcileSuite:
    """Master facade reconciling silent stream truncations against server-side reservation proofs."""

    def __init__(self, config: Optional[SilentEndReconcileConfig] = None) -> None:
        self._config = config or SilentEndReconcileConfig()
        self._watchdog = StreamTerminalWatchdog(self._config)
        self._verifier = ServerRuntimeVerifier(self._config)

    @property
    def watchdog(self) -> StreamTerminalWatchdog:
        """Access the stream terminal event watchdog."""
        return self._watchdog

    @property
    def verifier(self) -> ServerRuntimeVerifier:
        """Access the server-side runtime verifier."""
        return self._verifier

    def start_stream_turn(self, session_id: str, run_id: str) -> None:
        """Marks the initiation of a client SSE streaming turn."""
        self._watchdog.register_stream_start(session_id, run_id)

    def ingest_stream_event(
        self,
        session_id: str,
        run_id: str,
        event_name: str,
        event_id: Optional[str] = None,
    ) -> None:
        """Ingests an event chunk received from the transport layer."""
        self._watchdog.record_chunk_event(
            session_id=session_id,
            run_id=run_id,
            event_name=event_name,
            event_id=event_id,
        )

    def conclude_stream_transport(
        self,
        session_id: str,
        run_id: str,
        transport_reason: str = "HTTP EOF reached",
    ) -> Optional[ReconcileOutcome]:
        """Concludes the transport layer and executes reconciliation if no terminal event arrived.

        Args:
            session_id: Target session identifier.
            run_id: Agent execution turn identifier.
            transport_reason: Description of how transport ended (e.g. reader EOF).

        Returns:
            ReconcileOutcome if silent end detected; None if turn ended cleanly with terminal event.
        """
        ticket: Optional[SilentEndTicket] = self._watchdog.on_stream_transport_completed(
            session_id=session_id,
            run_id=run_id,
            transport_reason=transport_reason,
        )

        if ticket is None:
            # Clean completion with authentic business terminal event
            self._watchdog.reset_turn(session_id, run_id)
            return None

        # Silent end: execute server-side reconciliation probe
        outcome = self._verifier.reconcile_silent_end(ticket)
        if outcome.should_clear_loading_state:
            self._watchdog.reset_turn(session_id, run_id)
        return outcome

    def is_turn_terminal_delivered(self, session_id: str, run_id: str) -> bool:
        """Checks whether the specified turn has received an authentic terminal event."""
        return self._watchdog.has_terminal_received(session_id, run_id)

    def register_server_reservation(
        self,
        session_id: str,
        run_id: str,
        status: StreamRunStatus,
        final_output_digest: Optional[str] = None,
        error_diagnostic: Optional[str] = None,
    ) -> None:
        """Registers a server-side active operation reservation state."""
        reservation = ServerRunReservation(
            session_id=session_id,
            run_id=run_id,
            status=status,
            final_output_digest=final_output_digest,
            error_diagnostic=error_diagnostic,
        )
        self._verifier.register_server_reservation(reservation)
