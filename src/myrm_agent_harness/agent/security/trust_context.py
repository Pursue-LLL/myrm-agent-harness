"""Request trust context protocol for remote tool policy (harness-facing)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RequestTrustZone(str, Enum):
    LOCAL_TRUSTED = "local_trusted"
    REMOTE_EXPOSED = "remote_exposed"
    MANAGED = "managed"


@dataclass(frozen=True, slots=True)
class RequestTrustContext:
    """Propagated from agent-server request.state into harness run config."""

    trust_zone: RequestTrustZone
    admission_path: str
    restrict_destructive_tools: bool
    restrict_shell_tools: bool
    restrict_computer_use: bool

    @classmethod
    def from_admission(
        cls,
        *,
        trust_zone: str | None,
        admission_path: str | None,
    ) -> RequestTrustContext:
        zone = RequestTrustZone(trust_zone or RequestTrustZone.LOCAL_TRUSTED.value)
        remote = zone == RequestTrustZone.REMOTE_EXPOSED
        return cls(
            trust_zone=zone,
            admission_path=admission_path or "loopback_direct",
            restrict_destructive_tools=remote,
            restrict_shell_tools=remote,
            restrict_computer_use=remote,
        )


__all__ = ["RequestTrustContext", "RequestTrustZone"]
