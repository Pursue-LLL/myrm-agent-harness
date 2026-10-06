"""Data types and schemas for progressive CLI capability manifests and dry-run discovery.

Strictly typed, 0 Any. Implements llms.txt standard and non-executing metadata probing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class CliCapabilityCategory(StrEnum):
    """Categorical grouping for CLI tools."""

    SYSTEM_CORE = "system_core"
    DEVELOPER_TOOLS = "developer_tools"
    MEDIA_PROCESSING = "media_processing"
    DATA_ANALYSIS = "data_analysis"
    NETWORK_WEB = "network_web"
    SECURITY_AUDIT = "security_audit"


class CliToolSourceKind(StrEnum):
    """Execution backend / provisioning source for a CLI tool."""

    NATIVE_PATH = "native_path"
    SANDBOX_PORTABLE = "sandbox_portable"
    OCI_CONTAINER = "oci_container"
    PACKAGE_ECOSYSTEM = "package_ecosystem"


@dataclass(frozen=True)
class CliToolSource:
    """An install or execution source for a tool."""

    source_kind: CliToolSourceKind
    priority: int  # Higher number means higher priority
    command_prefix: list[str]
    is_available: bool = True
    estimated_latency_ms: int = 10


@dataclass(frozen=True)
class CliCapabilityEntry:
    """A single registered CLI tool entry in the capability catalog."""

    name: str
    category: CliCapabilityCategory
    short_summary: str
    detailed_usage: str
    tags: set[str] = field(default_factory=set)
    sources: list[CliToolSource] = field(default_factory=list)
    has_side_effects: bool = False
    requires_network: bool = False


@dataclass(frozen=True)
class DryRunProbeRequest:
    """Query to dry-run inspect a tool without executing it."""

    tool_name: str
    proposed_args: list[str] = field(default_factory=list)
    target_environment: str = "sandbox"


@dataclass(frozen=True)
class DryRunProbeResult:
    """Result of a non-executing dry-run probe."""

    tool_name: str
    is_supported: bool
    recommended_command: list[str]
    best_source_kind: CliToolSourceKind
    detailed_usage: str
    will_require_network: bool
    potential_side_effects: bool
    estimated_tokens_saved: int
    probe_notes: str


@dataclass(frozen=True)
class ManifestFormatConfig:
    """Configuration for rendering the progressive capability manifest."""

    max_entries_per_category: int = 20
    include_categories: set[CliCapabilityCategory] | None = None
    render_tags: bool = True
