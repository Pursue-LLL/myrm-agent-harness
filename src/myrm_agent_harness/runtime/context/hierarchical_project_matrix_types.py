"""Data contracts for Hierarchical Project Context Matrix and Dynamic Binding Gate.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- GlobalAgentTier: Tier 1: Global Agent Persona and innate capabilities.
- ProjectWorkspaceTier: Tier 2: Workspace Project instructions, directory boundary, and shared rules.
- SessionGoalTier: Tier 3: Transient session intent, prompt constraints, and immediate objective.
- HierarchicalContextMatrix: Composed 3-tier prompt context matrix optimized for KV-Cache prefix stability.
- AgentProjectBindingRecord: Dynamic binding entry associating an agent with a project workspace.
- WorkspaceSessionRef: Lightweight session reference used for workspace health and orphan analysis.
- WorkspaceHealthReport: Diagnostic health assessment of project sessions and orphan residue.

[POS]
Data contracts for Hierarchical Project Context Matrix and Dynamic Binding Gate.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GlobalAgentTier:
    """Tier 1: Global Agent Persona and innate capabilities."""

    agent_id: str
    persona_name: str
    system_prompt: str
    private_skills: tuple[str, ...]


@dataclass(frozen=True)
class ProjectWorkspaceTier:
    """Tier 2: Workspace Project instructions, directory boundary, and shared rules."""

    project_id: str
    project_name: str
    root_path: str
    project_instructions: str
    shared_artifacts_dir: str
    allowed_globs: tuple[str, ...]


@dataclass(frozen=True)
class SessionGoalTier:
    """Tier 3: Transient session intent, prompt constraints, and immediate objective."""

    session_id: str
    session_intent: str
    temporary_constraints: tuple[str, ...]
    active_task_summary: str


@dataclass(frozen=True)
class HierarchicalContextMatrix:
    """Composed 3-tier prompt context matrix optimized for KV-Cache prefix stability."""

    agent_tier: GlobalAgentTier
    project_tier: ProjectWorkspaceTier
    session_tier: SessionGoalTier
    rendered_prompt: str


@dataclass(frozen=True)
class AgentProjectBindingRecord:
    """Dynamic binding entry associating an agent with a project workspace."""

    binding_id: str
    agent_id: str
    project_id: str
    role_description: str
    is_active: bool
    created_at_utc: str


@dataclass(frozen=True)
class WorkspaceSessionRef:
    """Lightweight session reference used for workspace health and orphan analysis."""

    session_id: str
    project_id: str | None
    artifact_count: int
    last_active_at_utc: str
    is_archived: bool


@dataclass(frozen=True)
class WorkspaceHealthReport:
    """Diagnostic health assessment of project sessions and orphan residue."""

    project_id: str | None
    total_sessions: int
    orphan_session_ids: tuple[str, ...]
    stale_session_ids: tuple[str, ...]
    active_agents_count: int
    health_summary: str
