"""Context bundle specification types.

[INPUT]
- enum::StrEnum (POS: Python string enumeration)
- dataclasses::dataclass (POS: Python dataclass)

[OUTPUT]
- ContextScene: logical scenes mounted under one bundle volume
- ContextBundleSpec: immutable bundle identity and layout contract

[POS]
Framework-level context bundle specification. Pure types with no Agent or Server imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

CONTEXT_BUNDLE_SCHEMA_VERSION = 1
VOLUME_LAYOUT_VERSION = 1

DEFAULT_BUNDLE_ID = "default"


class ContextScene(StrEnum):
    """Logical scenes mounted under a single ContextBundle volume."""

    MEMORY = "memory"
    WORKSPACE = "workspace"


@dataclass(frozen=True, slots=True)
class ContextBundleSpec:
    """Immutable bundle contract shared by Harness volume layout and Server binding."""

    bundle_id: str = DEFAULT_BUNDLE_ID
    schema_version: int = CONTEXT_BUNDLE_SCHEMA_VERSION
    volume_layout_version: int = VOLUME_LAYOUT_VERSION
