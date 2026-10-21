"""Stubs and patch targets for the stdio launch gates (workspace trust + OSV malware check).

[INPUT]
- myrm_agent_harness.toolkits.mcp.transport::get_workspace_trust_gate (POS: gate the actor and tool enumeration both consult)
- myrm_agent_harness.toolkits.mcp.security::check_osv_malware (POS: OSV advisory lookup run before spawning stdio servers)

[OUTPUT]
- PATCH_OSV_CHECK / PATCH_TRUST_GATE: dotted targets that resolve at call time inside the launch-gate code
- RecordingTrustGate: trust gate that records every spawn request and allows or refuses it

[POS]
Harness pytest-only helper shared by the actor and the enumeration launch-gate tests.
"""

from __future__ import annotations

PATCH_OSV_CHECK = "myrm_agent_harness.toolkits.mcp.security.check_osv_malware"
PATCH_TRUST_GATE = "myrm_agent_harness.toolkits.mcp.transport.get_workspace_trust_gate"


class RecordingTrustGate:
    """A workspace trust gate that records every spawn request it is asked about."""

    def __init__(self, *, deny: bool, trust_level: str = "untrusted") -> None:
        self._deny = deny
        self._trust_level = trust_level
        self.requests: list[dict[str, object]] = []

    def get_trust_level(self) -> str:
        return self._trust_level

    def assert_mcp_spawn_allowed(self, **request: object) -> None:
        self.requests.append(request)
        if self._deny:
            raise PermissionError("workspace is not trusted")
