"""Data types and schemas for agent context ownership portable export and no-lock-in migration.

Provides machine-consumable schemas, integrity receipts, and selective redaction descriptors
to prove user ownership of their complete context layer (sessions, memories, skills, goals, automations).

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- ContextArtifactKind: Categorization of portable context layer artifacts.
- ExportScope: Filter criteria governing which context artifacts are included in the portable bundle.
- PortableContextItem: Normalized context artifact representation consumable across diverse agent runtimes.
- ExportIntegrityReceipt: Cryptographic tamper-evident receipt proving completeness and fidelity of the
  export.
- PortableContextBundle: Standard portable export bundle payload with versioned schema and handoff
  documentation.

[POS]
Data types and schemas for agent context ownership portable export and no-lock-in migration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ContextArtifactKind(StrEnum):
    """Categorization of portable context layer artifacts."""

    SESSION = "session"
    MEMORY = "memory"
    SKILL = "skill"
    GOAL = "goal"
    CRON_TASK = "cron_task"


@dataclass(frozen=True)
class ExportScope:
    """Filter criteria governing which context artifacts are included in the portable bundle."""

    target_session_ids: list[str] | None = None
    included_kinds: list[ContextArtifactKind] | None = None
    redact_secrets: bool = True
    max_items: int = 1000


@dataclass(frozen=True)
class PortableContextItem:
    """Normalized context artifact representation consumable across diverse agent runtimes."""

    item_id: str
    kind: ContextArtifactKind
    title: str
    content: str
    metadata: dict[str, str] = field(default_factory=dict)
    created_at_iso: str = ""


@dataclass(frozen=True)
class ExportIntegrityReceipt:
    """Cryptographic tamper-evident receipt proving completeness and fidelity of the export."""

    receipt_id: str
    exported_at_iso: str
    schema_version: str
    total_items: int
    kind_counts: dict[str, int]
    sha256_checksum: str
    redaction_applied: bool
    proof_statement: str


@dataclass(frozen=True)
class PortableContextBundle:
    """Standard portable export bundle payload with versioned schema and handoff documentation."""

    schema_version: str
    receipt: ExportIntegrityReceipt
    items: list[PortableContextItem]
    handoff_guide_markdown: str
