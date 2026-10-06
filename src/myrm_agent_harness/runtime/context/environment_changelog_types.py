"""Type definitions for dual-readable environment changelog and anti-amnesia recovery ledger.

Defines mutation kinds, structured changelog entries, consolidated environment state digests,
and anti-amnesia context rehydration payloads.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class EnvironmentMutationKind(StrEnum):
    """Classification of environment and sandbox mutations."""

    PACKAGE_INSTALL = "package_install"
    MCP_TOOL_MOUNT = "mcp_tool_mount"
    CONFIG_UPDATE = "config_update"
    ENV_VAR_CHANGE = "env_var_change"
    FILE_SYSTEM_MUTATION = "file_system_mutation"


class MutationActor(StrEnum):
    """Originator of the environment modification."""

    AGENT = "agent"
    USER = "user"
    SYSTEM = "system"


@dataclass(frozen=True)
class EnvironmentChangelogEntry:
    """Atomic structured ledger entry recording an environmental state mutation."""

    entry_id: str
    timestamp: float = field(default_factory=time.time)
    actor: MutationActor = MutationActor.AGENT
    kind: EnvironmentMutationKind = EnvironmentMutationKind.PACKAGE_INSTALL
    target_name: str = ""
    old_state: str | None = None
    new_state: str = ""
    rationale: str = ""
    is_verified: bool = True


@dataclass(frozen=True)
class EnvironmentStateDigest:
    """Consolidated state snapshot of the environment deduced from changelog history."""

    installed_packages: dict[str, str] = field(default_factory=dict)
    active_mcp_servers: list[str] = field(default_factory=list)
    effective_env_vars: dict[str, str] = field(default_factory=dict)
    recent_changes_count: int = 0
    last_mutation_timestamp: float | None = None
    summary_markdown: str = ""


@dataclass(frozen=True)
class RehydrationInjectionPayload:
    """Prompt-ready context payload for cross-session anti-amnesia rehydration."""

    digest: EnvironmentStateDigest
    prompt_block: str
    token_count_estimate: int
