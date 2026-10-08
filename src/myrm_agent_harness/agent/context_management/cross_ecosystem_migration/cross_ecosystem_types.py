"""Types for cross-ecosystem agent rule migration and compatibility inspector.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- EcosystemSpecKind: Source ecosystem of the imported rule definition.
- RuleSectionCategory: Semantic category of a rule directive block.
- DiscoveredEcosystemFile: Discovered foreign or native agent rule file.
- EcosystemConflictItem: Detected conflict or contradiction between multiple rule definitions.
- RuleMigrationReportReceipt: Auditable receipt from analyzing and consolidating multi-ecosystem rule files.

[POS]
Types for cross-ecosystem agent rule migration and compatibility inspector.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class EcosystemSpecKind(str, Enum):
    """Source ecosystem of the imported rule definition."""

    CLAUDE_CODE = "claude_code"
    CURSOR_RULES = "cursor_rules"
    CURSOR_MDC = "cursor_mdc"
    COPILOT_INSTRUCTIONS = "copilot_instructions"
    WINDSURF_RULES = "windsurf_rules"
    AGENTIC_AI_FOUNDATION = "agentic_ai_foundation"


class RuleSectionCategory(str, Enum):
    """Semantic category of a rule directive block."""

    PROJECT_OVERVIEW = "project_overview"
    BUILD_AND_TEST = "build_and_test"
    CODE_STYLE = "code_style"
    RESTRICTIONS_GUARD = "restrictions_guard"
    CUSTOM_DIRECTIVE = "custom_directive"


@dataclass(frozen=True)
class DiscoveredEcosystemFile:
    """Discovered foreign or native agent rule file."""

    file_path: str
    ecosystem: EcosystemSpecKind
    content: str
    digest: str
    parsed_sections: Dict[RuleSectionCategory, str] = field(default_factory=dict)


@dataclass(frozen=True)
class EcosystemConflictItem:
    """Detected conflict or contradiction between multiple rule definitions."""

    category: RuleSectionCategory
    file_a: str
    file_b: str
    conflict_description: str
    suggested_resolution: str


@dataclass(frozen=True)
class RuleMigrationReportReceipt:
    """Auditable receipt from analyzing and consolidating multi-ecosystem rule files."""

    workspace_root: str
    discovered_specs_count: int
    conflicts_count: int = 0
    discovered_files: list[DiscoveredEcosystemFile] = field(default_factory=list)
    conflicts: list[EcosystemConflictItem] = field(default_factory=list)
    consolidated_agents_md: str = ""
    manifest_hash: str = ""
    is_lossless: bool = True
