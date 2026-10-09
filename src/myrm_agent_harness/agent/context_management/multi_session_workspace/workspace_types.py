"""Contracts and data models for multi-session parallel workspace and root discovery.

[INPUT]
- None (pure domain types and enum contracts).

[OUTPUT]
- Exports enumerations and dataclasses for project root indicators,
  workspace grid layouts, concurrency slots, and cross-session reference bundles.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.multi_session_workspace
- Module: workspace_types.py
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Mapping, Optional, Sequence


class RootIndicatorKind(str, Enum):
    """Categorization of marker files denoting repository or package roots."""

    VCS = "vcs"
    BUILD_CONFIG = "build_config"
    MONOREPO_WORKSPACE = "monorepo_workspace"
    LANGUAGE_SPEC = "language_spec"


class GridLayoutType(str, Enum):
    """Layout viewport configuration for parallel session decks."""

    SINGLE = "single"
    SPLIT_HORIZONTAL = "split_horizontal"
    SPLIT_VERTICAL = "split_vertical"
    QUAD_GRID = "quad_grid"
    TABBED = "tabbed"


class SlotRoleTag(str, Enum):
    """Semantic role of a docked session within the parallel grid."""

    PRIMARY_WORKER = "primary_worker"
    INTERACTIVE_COPILOT = "interactive_copilot"
    BACKGROUND_AUDITOR = "background_auditor"
    DOCS_EXPLORER = "docs_explorer"


@dataclass(frozen=True)
class DiscoveredRootResult:
    """Outcome of heuristic project root sniffing."""

    starting_path: Path
    discovered_root: Path
    confidence_score: float
    indicators_found: Sequence[str]
    is_monorepo_root: bool
    traversal_depth: int
    diagnostic_reason: str


@dataclass(frozen=True)
class WorkspaceSlot:
    """Individual viewport slot docking an active or background session."""

    slot_id: str
    assigned_session_id: Optional[str]
    is_focused: bool
    slot_title: str
    role_tag: SlotRoleTag


@dataclass(frozen=True)
class WorkspaceDeckState:
    """Complete layout snapshot of the parallel multi-session grid."""

    layout_type: GridLayoutType
    slots: Sequence[WorkspaceSlot]
    active_slot_id: str
    total_active_sessions: int


@dataclass(frozen=True)
class CrossSessionArtifactItem:
    """Artifact or output generated in a peer session available for reference."""

    artifact_id: str
    name: str
    mime_type: str
    summary_preview: str
    uri: Optional[str] = None


@dataclass(frozen=True)
class CrossSessionReferenceBundle:
    """Encapsulates peer session conclusions, deliverables, and summaries for injection."""

    source_session_id: str
    target_session_id: str
    session_title: str
    key_findings_summary: str
    salvaged_artifacts: Sequence[CrossSessionArtifactItem] = field(default_factory=tuple)
    reference_digest: str = ""


@dataclass(frozen=True)
class MultiSessionWorkspaceConfig:
    """Configuration options governing root sniffing, layouts, and cross-session extraction."""

    max_upward_traversal_depth: int = 6
    monorepo_indicators: Sequence[str] = (
        "pnpm-workspace.yaml",
        "lerna.json",
        "rush.json",
        "nx.json",
    )
    standard_root_indicators: Mapping[str, RootIndicatorKind] = field(
        default_factory=lambda: {
            ".git": RootIndicatorKind.VCS,
            ".hg": RootIndicatorKind.VCS,
            ".svn": RootIndicatorKind.VCS,
            "pyproject.toml": RootIndicatorKind.BUILD_CONFIG,
            "package.json": RootIndicatorKind.BUILD_CONFIG,
            "Cargo.toml": RootIndicatorKind.BUILD_CONFIG,
            "go.mod": RootIndicatorKind.BUILD_CONFIG,
            "pom.xml": RootIndicatorKind.BUILD_CONFIG,
            "build.gradle": RootIndicatorKind.BUILD_CONFIG,
            "CMakeLists.txt": RootIndicatorKind.BUILD_CONFIG,
        }
    )
    max_slots_allowed: int = 4
    max_cross_session_tokens: int = 1500
