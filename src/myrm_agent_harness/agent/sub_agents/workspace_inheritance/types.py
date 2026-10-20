"""Domain models and types for Subagent Workspace Context Inheritance & Prompt Enrichment (Item 56).

Defines workspace context source types, priority chains (.rules > AGENTS.md > README.md),
rule snippets, token budget configuration, enrichment results, and inheritance audit records.

[INPUT]
- __future__
- time
- dataclasses
- enum

[OUTPUT]
- ContextSourceType
- RulePriority
- SubagentRole
- ContextRuleSnippet
- WorkspaceInheritanceConfig
- EnrichmentResult
- InheritanceAuditRecord

[POS]
Domain models and types for Subagent Workspace Context Inheritance & Prompt Enrichment (Item 56).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class ContextSourceType(StrEnum):
    """Source classifications for inherited workspace context files."""

    RULES = ".rules"
    AGENTS_MD = "AGENTS.md"
    README_MD = "README.md"
    CUSTOM = "custom"


class RulePriority(StrEnum):
    """Priority weights used during context budget capping and differential pruning."""

    CRITICAL = "critical"  # Architectural redlines, security boundaries, no-delete invariants
    HIGH = "high"          # Code conventions, typed annotations, test standards
    NORMAL = "normal"      # Workflow habits, PR guidelines, module organization
    LOW = "low"            # General background, descriptions, notes


class SubagentRole(StrEnum):
    """Role classifications determining specialized context enrichment focus."""

    WORKER = "worker"
    REVIEWER = "reviewer"
    SPECIALIST = "specialist"
    COORDINATOR = "coordinator"


@dataclass(frozen=True)
class ContextRuleSnippet:
    """Extracted rule or constraint section from a workspace context file."""

    source_type: ContextSourceType
    file_path: str
    priority: RulePriority
    title: str
    content: str
    token_count: int


@dataclass
class WorkspaceInheritanceConfig:
    """Configuration governing context discovery, priorities, and token budget."""

    max_context_tokens: int = 2000
    priority_chain: list[ContextSourceType] = field(
        default_factory=lambda: [
            ContextSourceType.RULES,
            ContextSourceType.AGENTS_MD,
            ContextSourceType.README_MD,
        ]
    )
    enable_compact_summarization: bool = True
    auto_discover: bool = True


@dataclass(frozen=True)
class EnrichmentResult:
    """Outcome of enriching a subagent's system prompt with workspace context."""

    original_prompt: str
    enriched_prompt: str
    injected_token_count: int
    is_compacted: bool
    matched_sources: list[str]
    applied_snippets: list[ContextRuleSnippet]


@dataclass(frozen=True)
class InheritanceAuditRecord:
    """Persistent audit entry recording an inheritance execution for subagents."""

    audit_id: str
    workspace_root: str
    subagent_role: SubagentRole
    injected_tokens: int
    compacted: bool
    timestamp: float = field(default_factory=time.time)
    matched_files: list[str] = field(default_factory=list)
