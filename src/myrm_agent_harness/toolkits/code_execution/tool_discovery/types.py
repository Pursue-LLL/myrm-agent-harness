"""CLI tool discovery data types.

[INPUT]
(none)

[OUTPUT]
ToolDefinition: Predefined tool entry in the tool catalog (id / bin_names / description / tags / install_hints)
DetectedTool: Confirmed CLI tool instance on the host machine (with actual bin_path)

[POS]
Data type layer for CLI tool discovery. Defines ToolDefinition (catalog entry)
and DetectedTool (detection result) as immutable dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ToolDefinition:
    """Pre-defined CLI tool entry in the catalog."""

    id: str
    bin_names: tuple[str, ...]
    desc_en: str
    desc_zh: str
    tags: frozenset[str] = field(default_factory=frozenset)
    install_hints: dict[str, str] = field(default_factory=dict)
    """Platform-specific install commands. Key: platform.system() value (Darwin/Linux/Windows)."""


@dataclass(frozen=True)
class DetectedTool:
    """A CLI tool that was confirmed present on the host system."""

    id: str
    bin_name: str
    bin_path: Path
    desc_en: str
    desc_zh: str
    tags: frozenset[str] = field(default_factory=frozenset)
