"""Strongly typed data contracts for the Source-engine style unified Convar system.

Benchmarked against Can Bölük's Harness Playbook Chapter 3.3 Control Plane Convars:
- Declares configuration variable metadata, default values, documentation, and bitflags in one place.
- Eliminates multi-layered boilerplate setters/getters across environment, DB, and state dictionaries.
- Supports hierarchical scoped inheritance and dirty-tracking across subagents.

[OUTPUT]
- ConvarType: Supported primitive types for Convars (STR, INT, FLOAT, BOOL).
- ConvarFlags: Bitwise configuration behavior flags (ARCHIVE, REPLICATED, SESSION_ONLY, READ_ONLY).
- ConvarDefinition: Immutable schema definition for a declared console variable.
- ConvarSnapshot: Evaluated state snapshot including dirty status and scope origin.

[INPUT]
- __future__
- time
- dataclasses
- enum

[OUTPUT]
- ConvarType
- ConvarFlags
- ConvarDefinition
- ConvarSnapshot

[POS]
Strongly typed data contracts for the Source-engine style unified Convar system.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import IntFlag, StrEnum


class ConvarType(StrEnum):
    """Primitive data type validation contract for Convars."""

    STR = "str"
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"


class ConvarFlags(IntFlag):
    """Behavioral bitflags defining persistence, replication, and mutability."""

    NONE = 0
    ARCHIVE = 1 << 0
    """Persisted to disk configuration (.cfg) or relational database."""

    REPLICATED = 1 << 1
    """Propagated transparently from parent session to child subagents."""

    SESSION_ONLY = 1 << 2
    """Transient lifecycle; reset automatically upon session termination."""

    READ_ONLY = 1 << 3
    """Immutable at runtime; can only be specified at process initialization."""


@dataclass(frozen=True)
class ConvarDefinition:
    """Immutable prototype declaration for a registered console variable."""

    name: str
    convar_type: ConvarType
    default_value: str
    help_text: str
    flags: ConvarFlags = ConvarFlags.NONE
    min_val: float | None = None
    max_val: float | None = None


@dataclass(frozen=True)
class ConvarSnapshot:
    """Evaluated runtime state of a Convar in a specific scope."""

    name: str
    raw_value: str
    typed_value: str | int | float | bool
    is_dirty: bool
    scope_name: str
    updated_at: float = field(default_factory=time.time)
