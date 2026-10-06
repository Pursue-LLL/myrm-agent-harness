# [POS] src/myrm_agent_harness/toolkits/memory/openclaw_adapter/types.py
# [INPUT] dataclasses, enum.StrEnum, datetime, typing
# [OUTPUT] OpenClawVersion, OpenClawSessionNode, OpenClawMemoryEntryV2, RescueReport, OpenClawParsedBundle

from dataclasses import dataclass, field
from enum import StrEnum


class OpenClawVersion(StrEnum):
    """Supported OpenClaw data schema versions."""

    V1 = "1.x"
    V2 = "2.x"


@dataclass(frozen=True)
class OpenClawSessionNode:
    """Represents a session node in OpenClaw 2.0 multi-user & Swarm topology tree."""

    session_id: str
    title: str
    parent_session_id: str | None = None
    swarm_agent_id: str | None = None
    owner_id: str = "default_user"
    creator_id: str = "default_user"
    messages: list[dict[str, str]] = field(default_factory=list)
    created_at: str = ""
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class OpenClawMemoryEntryV2:
    """Represents a structured memory entry in OpenClaw 2.0."""

    entry_id: str
    content: str
    category: str
    scope: str = "shared"
    target_agent_id: str | None = None
    importance: float = 0.7
    created_at: str = ""
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RescueReport:
    """Diagnostics and telemetry generated during crash recovery extraction."""

    db_path: str
    is_sqlite_corrupt: bool
    integrity_check_output: str
    total_rows_scanned: int
    recovered_count: int
    corrupted_rows_skipped: int
    rescue_success_rate: float


@dataclass(frozen=True)
class OpenClawParsedBundle:
    """Unified bundle containing parsed OpenClaw sessions, memories, and rescue diagnostics."""

    version: OpenClawVersion
    sessions: list[OpenClawSessionNode] = field(default_factory=list)
    memories: list[OpenClawMemoryEntryV2] = field(default_factory=list)
    rescue_report: RescueReport | None = None
    warnings: list[str] = field(default_factory=list)
