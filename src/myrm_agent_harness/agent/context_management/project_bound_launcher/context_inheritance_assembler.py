"""Context inheritance assembler for project-bound sessions.

[INPUT]
- launcher_types: ProjectMetadataSnapshot, InheritedContextFrame, InheritanceStatus.

[OUTPUT]
- ContextInheritanceAssembler: Synthesizes inherited project goals, descriptions,
  and filesystem locations into a high signal-to-noise initial prompt block.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.project_bound_launcher
- Module: context_inheritance_assembler.py
"""

from typing import List, Optional
from myrm_agent_harness.agent.context_management.project_bound_launcher.launcher_types import (
    InheritedContextFrame,
    InheritanceStatus,
    ProjectMetadataSnapshot,
)


class ContextInheritanceAssembler:
    """Assembles prompt and environment context frames from project and workspace metadata."""

    def assemble(
        self,
        project: Optional[ProjectMetadataSnapshot],
        effective_cwd: str,
        effective_agent_id: str,
        git_branch: str = "",
        git_repo_root: str = "",
        max_chars: int = 1200,
    ) -> InheritedContextFrame:
        """Constructs an InheritedContextFrame to prime the first turn of a conversation.

        Args:
            project: Optional project snapshot containing domain goals and descriptions.
            effective_cwd: Resolved working directory for tool execution.
            effective_agent_id: Resolved agent profile executing the session.
            git_branch: Resolved git branch name if applicable.
            git_repo_root: Resolved git root directory if applicable.
            max_chars: Maximum allowable character length for the prompt injection block.

        Returns:
            An immutable InheritedContextFrame instance.
        """
        lines: List[str] = ["[PROJECT_WORKSPACE_CONTEXT]"]
        lines.append(f"- Working Directory: {effective_cwd}")
        if git_branch:
            lines.append(f"- Git Branch: {git_branch}")
        if git_repo_root:
            lines.append(f"- Git Repo Root: {git_repo_root}")

        if project is None:
            status = InheritanceStatus.NONE
            lines.append("- Project Binding: None (Standalone Quick Chat)")
            lines.append("[/PROJECT_WORKSPACE_CONTEXT]")
            block = "\n".join(lines)
            return InheritedContextFrame(
                project_id=None,
                workspace_path=effective_cwd,
                agent_id=effective_agent_id,
                context_prompt_block=block,
                git_branch=git_branch,
                git_repo_root=git_repo_root,
                inheritance_status=status,
            )

        lines.append(f"- Project: {project.name} (ID: {project.project_id})")
        if project.goal_summary:
            clean_goal = project.goal_summary.strip().replace("\n", " ")
            lines.append(f"- Goal Summary: {clean_goal}")
        if project.description:
            clean_desc = project.description.strip().replace("\n", " ")
            lines.append(f"- Description: {clean_desc}")
        if project.tags:
            lines.append(f"- Tags: {', '.join(project.tags)}")

        lines.append("[/PROJECT_WORKSPACE_CONTEXT]")
        full_block = "\n".join(lines)

        # Truncate if exceeding configured ceiling while preserving closing tag
        if len(full_block) > max_chars:
            cutoff = max_chars - len("\n... (truncated)\n[/PROJECT_WORKSPACE_CONTEXT]")
            truncated_body = full_block[:cutoff].rstrip()
            full_block = f"{truncated_body}\n... (truncated)\n[/PROJECT_WORKSPACE_CONTEXT]"
            status = InheritanceStatus.INHERITED_PARTIAL
        else:
            status = InheritanceStatus.INHERITED_FULL

        return InheritedContextFrame(
            project_id=project.project_id,
            workspace_path=effective_cwd,
            agent_id=effective_agent_id,
            context_prompt_block=full_block,
            git_branch=git_branch,
            git_repo_root=git_repo_root,
            inheritance_status=status,
        )
