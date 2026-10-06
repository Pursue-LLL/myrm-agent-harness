"""Hierarchical Project Context Matrix and Agent Dynamic Binding Gate.

Provides 3-tier prompt composition (Global Persona -> Project Rules -> Session Goals)
optimized for prefix KV-Cache preservation, dynamic multi-agent to project binding,
and workspace session health and orphan garbage detection.
"""

from __future__ import annotations

from typing import ClassVar

from myrm_agent_harness.runtime.context.hierarchical_project_matrix_types import (
    AgentProjectBindingRecord,
    GlobalAgentTier,
    HierarchicalContextMatrix,
    ProjectWorkspaceTier,
    SessionGoalTier,
    WorkspaceHealthReport,
    WorkspaceSessionRef,
)

__all__ = [
    "AgentDynamicBindingGate",
    "AgentProjectBindingRecord",
    "GlobalAgentTier",
    "HierarchicalContextMatrix",
    "HierarchicalContextMatrixComposer",
    "ProjectWorkspaceTier",
    "SessionGoalTier",
    "WorkspaceHealthAndOrphanDetector",
    "WorkspaceHealthReport",
    "WorkspaceSessionRef",
]


class HierarchicalContextMatrixComposer:
    """Composes layered 3-tier prompt context preserving KV-Cache affinity."""

    @classmethod
    def compose_matrix(
        cls,
        *,
        agent_tier: GlobalAgentTier,
        project_tier: ProjectWorkspaceTier,
        session_tier: SessionGoalTier,
    ) -> HierarchicalContextMatrix:
        """Synthesizes structured context hierarchy XML."""
        lines: list[str] = [
            '<hierarchical_context_matrix version="1.0">',
            f'  <tier_1_global_agent agent_id="{agent_tier.agent_id}" persona="{agent_tier.persona_name}">',
            f"    <system_prompt>{agent_tier.system_prompt}</system_prompt>",
            f"    <private_skills>{', '.join(agent_tier.private_skills)}</private_skills>",
            "  </tier_1_global_agent>",
            f'  <tier_2_project_workspace project_id="{project_tier.project_id}" name="{project_tier.project_name}" root="{project_tier.root_path}">',
            f"    <instructions>{project_tier.project_instructions}</instructions>",
            f"    <shared_artifacts_dir>{project_tier.shared_artifacts_dir}</shared_artifacts_dir>",
            f"    <allowed_globs>{', '.join(project_tier.allowed_globs)}</allowed_globs>",
            "  </tier_2_project_workspace>",
            f'  <tier_3_session_goal session_id="{session_tier.session_id}" intent="{session_tier.session_intent}">',
            f"    <active_task_summary>{session_tier.active_task_summary}</active_task_summary>",
            "    <temporary_constraints>",
        ]
        for c in session_tier.temporary_constraints:
            lines.append(f"      <constraint>{c}</constraint>")
        lines.append("    </temporary_constraints>")
        lines.append("  </tier_3_session_goal>")
        lines.append("</hierarchical_context_matrix>")

        rendered = "\n".join(lines)
        return HierarchicalContextMatrix(
            agent_tier=agent_tier,
            project_tier=project_tier,
            session_tier=session_tier,
            rendered_prompt=rendered,
        )


class AgentDynamicBindingGate:
    """Manages many-to-many dynamic associations between agents and workspace projects."""

    def __init__(self) -> None:
        self._bindings: dict[str, AgentProjectBindingRecord] = {}

    @staticmethod
    def _make_key(agent_id: str, project_id: str) -> str:
        return f"{agent_id}::{project_id}"

    def bind_agent(
        self,
        *,
        agent_id: str,
        project_id: str,
        role_description: str,
        created_at_utc: str,
    ) -> AgentProjectBindingRecord:
        """Mounts an agent into a workspace project with explicit role definition."""
        key = self._make_key(agent_id, project_id)
        record = AgentProjectBindingRecord(
            binding_id=f"bind_{key}",
            agent_id=agent_id,
            project_id=project_id,
            role_description=role_description,
            is_active=True,
            created_at_utc=created_at_utc,
        )
        self._bindings[key] = record
        return record

    def unbind_agent(self, agent_id: str, project_id: str) -> bool:
        """Removes the association between an agent and a workspace project."""
        key = self._make_key(agent_id, project_id)
        if key in self._bindings:
            del self._bindings[key]
            return True
        return False

    def is_agent_bound(self, agent_id: str, project_id: str) -> bool:
        key = self._make_key(agent_id, project_id)
        rec = self._bindings.get(key)
        return rec is not None and rec.is_active

    def list_bindings_for_project(self, project_id: str) -> tuple[AgentProjectBindingRecord, ...]:
        return tuple(b for b in self._bindings.values() if b.project_id == project_id and b.is_active)

    def list_bindings_for_agent(self, agent_id: str) -> tuple[AgentProjectBindingRecord, ...]:
        return tuple(b for b in self._bindings.values() if b.agent_id == agent_id and b.is_active)


class WorkspaceHealthAndOrphanDetector:
    """Scans workspace projects for detached orphan sessions and stagnant residues."""

    DEFAULT_ORPHAN_CRITERIA_DESC: ClassVar[str] = (
        "Sessions unlinked to project or inactive with zero produced artifacts."
    )

    @classmethod
    def evaluate_workspace_health(
        cls,
        *,
        project_id: str | None,
        sessions: tuple[WorkspaceSessionRef, ...],
        bindings: tuple[AgentProjectBindingRecord, ...],
    ) -> WorkspaceHealthReport:
        """Evaluates session attachment and discovers orphan candidate sessions."""
        orphan_ids: list[str] = []
        stale_ids: list[str] = []

        active_bound_agents = {b.agent_id for b in bindings if b.is_active}

        for s in sessions:
            # Orphan condition: session has no project or belongs to non-matching project with 0 artifacts
            if s.project_id is None or (project_id is not None and s.project_id != project_id):
                orphan_ids.append(s.session_id)
            elif s.is_archived and s.artifact_count == 0:
                stale_ids.append(s.session_id)

        status_msg = (
            f"Workspace '{project_id or 'all'}' has {len(sessions)} sessions, "
            f"{len(orphan_ids)} orphans, {len(stale_ids)} stale entries, "
            f"and {len(active_bound_agents)} active agents."
        )

        return WorkspaceHealthReport(
            project_id=project_id,
            total_sessions=len(sessions),
            orphan_session_ids=tuple(orphan_ids),
            stale_session_ids=tuple(stale_ids),
            active_agents_count=len(active_bound_agents),
            health_summary=status_msg,
        )
