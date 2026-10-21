"""Incident domain types for cron reliability and signature dedup.

Physical separation from runtime execution logs ensures failure incidents
persist across reboots and support operator acknowledgment (ACK) silencing.

[OUTPUT]
- IncidentState: Lifecycle states for an incident.
- FailureType: Classified category of a job execution failure.
- CronIncident: Durable incident record representation.
- incident_to_dict: Serialises a CronIncident to dict.
- dict_to_incident: Deserialises a dict to CronIncident.

[INPUT]
- __future__
- dataclasses
- datetime
- typing

[OUTPUT]
- IncidentState
- FailureType
- VALID_INCIDENT_STATES
- VALID_FAILURE_TYPES
- CronIncident
- incident_to_dict
- dict_to_incident

[POS]
Incident domain types for cron reliability and signature dedup.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

IncidentState = Literal["detected", "alerted", "resolved", "closed"]

FailureType = Literal[
    "rate_limit",
    "timeout",
    "auth",
    "delivery",
    "config",
    "script",
    "agent",
    "false_positive",
    "unknown",
]

VALID_INCIDENT_STATES: tuple[IncidentState, ...] = (
    "detected",
    "alerted",
    "resolved",
    "closed",
)

VALID_FAILURE_TYPES: tuple[FailureType, ...] = (
    "rate_limit",
    "timeout",
    "auth",
    "delivery",
    "config",
    "script",
    "agent",
    "false_positive",
    "unknown",
)


@dataclass(frozen=True, slots=True)
class CronIncident:
    """Durable incident for a recurring cron job failure.

    Keyed by (job_id, error_sig) to deduplicate repetitive failures and
    prevent alert fatigue.
    """

    id: str
    job_id: str
    error_sig: str
    state: IncidentState
    failure_type: FailureType
    first_seen_at: datetime
    last_seen_at: datetime
    error: str
    output_file: str | None = None
    alerted_at: datetime | None = None
    acked_at: datetime | None = None
    closed_at: datetime | None = None


def incident_to_dict(inc: CronIncident) -> dict[str, str | None]:
    """Convert a CronIncident to a JSON-compatible dictionary."""
    return {
        "id": inc.id,
        "job_id": inc.job_id,
        "error_sig": inc.error_sig,
        "state": inc.state,
        "failure_type": inc.failure_type,
        "first_seen_at": inc.first_seen_at.isoformat(),
        "last_seen_at": inc.last_seen_at.isoformat(),
        "error": inc.error,
        "output_file": inc.output_file,
        "alerted_at": inc.alerted_at.isoformat() if inc.alerted_at else None,
        "acked_at": inc.acked_at.isoformat() if inc.acked_at else None,
        "closed_at": inc.closed_at.isoformat() if inc.closed_at else None,
    }


def dict_to_incident(d: dict[str, str | None]) -> CronIncident:
    """Construct a CronIncident from a serialized dictionary."""

    def _parse_dt(raw: str | None) -> datetime | None:
        if not raw:
            return None
        dt = datetime.fromisoformat(raw)
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)

    first_seen = _parse_dt(d["first_seen_at"])
    last_seen = _parse_dt(d["last_seen_at"])
    if first_seen is None or last_seen is None:
        raise ValueError("first_seen_at and last_seen_at are mandatory")

    state_raw = d.get("state", "detected")
    state: IncidentState = (
        state_raw if state_raw in VALID_INCIDENT_STATES else "detected"  # type: ignore[assignment]
    )

    ftype_raw = d.get("failure_type", "unknown")
    failure_type: FailureType = (
        ftype_raw if ftype_raw in VALID_FAILURE_TYPES else "unknown"  # type: ignore[assignment]
    )

    return CronIncident(
        id=str(d.get("id", "")),
        job_id=str(d.get("job_id", "")),
        error_sig=str(d.get("error_sig", "")),
        state=state,
        failure_type=failure_type,
        first_seen_at=first_seen,
        last_seen_at=last_seen,
        error=str(d.get("error", "")),
        output_file=d.get("output_file"),
        alerted_at=_parse_dt(d.get("alerted_at")),
        acked_at=_parse_dt(d.get("acked_at")),
        closed_at=_parse_dt(d.get("closed_at")),
    )
