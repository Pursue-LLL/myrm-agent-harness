"""Protocol contract for durable cron failure incidents ledger.

[OUTPUT]
- IncidentStore: Unified contract for persisting, deduplicating and acknowledging cron incidents.

[INPUT]
- __future__
- typing

[OUTPUT]
- IncidentStore

[POS]
Protocol contract for durable cron failure incidents ledger.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from myrm_agent_harness.toolkits.cron.incident_types import (
    CronIncident,
    FailureType,
    IncidentState,
)


@runtime_checkable
class IncidentStore(Protocol):
    """Unified persistence and lifecycle management contract for cron incidents."""

    async def upsert_incident(
        self,
        job_id: str,
        error: str,
        *,
        failure_type: FailureType | None = None,
        output_file: str | None = None,
    ) -> tuple[CronIncident, bool]:
        """Record or refresh an incident for (job_id, error_signature).

        Returns:
            tuple[CronIncident, bool]: The current incident object and a flag
            indicating if it is newly created or reopened from resolved.
        """
        ...

    async def set_incident_state(
        self,
        incident_id: str,
        state: IncidentState,
    ) -> bool:
        """Transition an incident lifecycle state.

        Returns:
            bool: True if transition occurred, False otherwise.
        """
        ...

    async def ack_incident(self, incident_id: str) -> bool:
        """Acknowledge (close) an incident to silence future per-run alerts.

        Returns:
            bool: True if closed, False if already closed or missing.
        """
        ...

    async def close_incidents_for_recovered_job(self, job_id: str) -> int:
        """Mark all open ('detected', 'alerted') incidents for job_id as 'resolved'.

        Returns:
            int: Number of resolved incidents.
        """
        ...

    async def list_incidents(
        self,
        *,
        state: IncidentState | None = None,
        job_id: str | None = None,
        limit: int | None = None,
    ) -> list[CronIncident]:
        """List incidents ordered by most recent activity first."""
        ...

    async def get_incident(self, incident_id: str) -> CronIncident | None:
        """Retrieve a specific incident by its unique id."""
        ...

    async def count_incidents(
        self,
        *,
        state: IncidentState | None = None,
        job_id: str | None = None,
    ) -> int:
        """Count incidents matching optional criteria."""
        ...
