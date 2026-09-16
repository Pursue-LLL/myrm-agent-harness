"""Team-shared conversation identity scope — channel compartment contract.

A team-shared identity lets one agent act as a stable teammate inside a group
conversation: everyone in the group talks to the same identity, while private
compartments (DMs, owner data) stay unreachable from the shared side.

This module is deliberately tiny and product-agnostic:

- No tenant / organization fields (harness is single-sandbox; multi-sandbox
  orchestration lives outside the framework).
- No tools, no middleware wiring, no Turn1 surface (zero prompt-cache impact).
- Pure deterministic helpers only; the business layer owns inheritance rules
  (e.g. baseline default vs per-channel independent) and credential routing.

[INPUT]
- Plain scope inputs from the business layer (no framework imports needed).

[OUTPUT]
- TeamIdentityScope: PERSONAL (owner-private) / SHARED (team compartment).
- CredentialTrack: PERSONAL (owner credentials) / SHARED (channel credentials).
- TeamIdentitySpec: frozen compartment contract for one resolved turn.
- memory_namespace_for(): sanitized ``ident:<id>`` namespace derivation.
- credential_track_for(): deterministic track selection helper.

[POS]
Layer 4 security domain companion to channel_presets (channel posture) and
mcp_approval_identity (MCP confused-deputy scope). This module answers "which
compartment does this turn belong to", the others answer "what may it do".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum, unique


@unique
class TeamIdentityScope(StrEnum):
    """Conversation compartment a turn executes in."""

    PERSONAL = "personal"
    SHARED = "shared"


@unique
class CredentialTrack(StrEnum):
    """Which credential pool a turn may draw from."""

    PERSONAL = "personal"
    SHARED = "shared"


_IDENTITY_ID_PATTERN: re.Pattern[str] = re.compile(r"[^a-zA-Z0-9_-]")
_IDENTITY_ID_MAX_LEN = 64
IDENTITY_NAMESPACE_PREFIX = "ident"


def sanitize_identity_id(raw: str) -> str:
    """Return a namespace-safe identity id, falling back to ``baseline``."""
    cleaned = _IDENTITY_ID_PATTERN.sub("", raw.strip().lower())
    if not cleaned:
        return "baseline"
    return cleaned[:_IDENTITY_ID_MAX_LEN]


def memory_namespace_for(identity_id: str) -> str:
    """Derive the memory compartment namespace for a team identity."""
    return f"{IDENTITY_NAMESPACE_PREFIX}:{sanitize_identity_id(identity_id)}"


def credential_track_for(*, is_group: bool, scope: TeamIdentityScope) -> CredentialTrack:
    """Select the credential track for a turn.

    Group turns under a shared identity must never touch owner-personal
    credentials; everything else stays on the personal track.
    """
    if is_group and scope == TeamIdentityScope.SHARED:
        return CredentialTrack.SHARED
    return CredentialTrack.PERSONAL


@dataclass(frozen=True, slots=True)
class TeamIdentitySpec:
    """Frozen compartment contract for one resolved turn.

    Attributes:
        scope: PERSONAL (owner-private) or SHARED (team compartment).
        identity_id: Stable identity id (renames change display name only).
        credential_track: Credential pool the turn may draw from.
        memory_namespace: Memory compartment namespace (``ident:<id>``).
        is_fallback: True when no binding existed and the default applies.
    """

    scope: TeamIdentityScope = TeamIdentityScope.PERSONAL
    identity_id: str = "baseline"
    credential_track: CredentialTrack = CredentialTrack.PERSONAL
    memory_namespace: str = "ident:baseline"
    is_fallback: bool = True

    def __post_init__(self) -> None:
        clean_id = sanitize_identity_id(self.identity_id)
        object.__setattr__(self, "identity_id", clean_id)
        expected_ns = memory_namespace_for(clean_id)
        if self.memory_namespace != expected_ns:
            object.__setattr__(self, "memory_namespace", expected_ns)
