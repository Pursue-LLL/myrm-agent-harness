"""Session keyword resurrection engine for seamless historical agent revival.

Restores complete working context, project workspace anchors, conversation transcripts,
and pending task goals from archived sessions, generating breakpoint prompts for seamless continuation.
"""

from __future__ import annotations

import time

from .project_hierarchy_session_index import ProjectHierarchySessionIndex
from .project_hierarchy_session_types import (
    ArchivedSessionNode,
    HierarchyHitKind,
    ProjectNode,
    ResurrectionContextBundle,
    ResurrectionStatus,
    TaskNode,
)


class SessionKeywordResurrectionEngine:
    """Orchestrates seamless context restoration and agent resurrection from archived sessions."""

    def __init__(
        self,
        index: ProjectHierarchySessionIndex | None = None,
    ) -> None:
        self._index = index or ProjectHierarchySessionIndex()

    @property
    def index(self) -> ProjectHierarchySessionIndex:
        """Underlying hierarchy search index."""
        return self._index

    def resurrect_session(
        self,
        session_id: str,
        continuation_instruction: str | None = None,
    ) -> ResurrectionContextBundle:
        """Restores a session breakpoint into an executable continuation bundle."""
        session = self._index.get_session(session_id)
        if not session:
            # Session not found error bundle
            dummy_proj = self._index.get_project("") or self._create_fallback_project()
            dummy_task = self._index.get_task("") or self._create_fallback_task()
            dummy_sess = self._create_fallback_session(session_id)
            return ResurrectionContextBundle(
                session_id=session_id,
                project=dummy_proj,
                task=dummy_task,
                session=dummy_sess,
                messages=(),
                resurrected_at=time.time(),
                status=ResurrectionStatus.FAILED,
                resurrection_prompt="",
                restored_tokens=0,
            )

        project = self._index.get_project(session.project_id) or self._create_fallback_project(
            session.project_id
        )
        task = self._index.get_task(session.task_id) or self._create_fallback_task(
            session.task_id, session.project_id
        )
        messages = self._index.get_messages(session_id)

        prompt = self._build_resurrection_prompt(
            project_name=project.name,
            workspace_path=project.workspace_path,
            task_title=task.title,
            session_title=session.title,
            checkpoint_summary=session.checkpoint_summary,
            message_count=len(messages),
            continuation_instruction=continuation_instruction,
        )

        return ResurrectionContextBundle(
            session_id=session_id,
            project=project,
            task=task,
            session=session,
            messages=messages,
            resurrected_at=time.time(),
            status=ResurrectionStatus.READY,
            resurrection_prompt=prompt,
            restored_tokens=session.total_tokens,
        )

    def search_and_resurrect_best(
        self,
        query: str,
        continuation_instruction: str | None = None,
        project_id: str | None = None,
    ) -> ResurrectionContextBundle | None:
        """Finds the most relevant historical session via keyword search and resurrects it."""
        search_res = self._index.search(query, project_id=project_id)
        if not search_res.groups:
            return None

        # Look for the top-scoring session hit
        for group in search_res.groups:
            for hit in group.matches:
                if hit.kind in (HierarchyHitKind.SESSION, HierarchyHitKind.MESSAGE):
                    target_session_id = hit.session_id
                    if target_session_id:
                        return self.resurrect_session(
                            target_session_id,
                            continuation_instruction=continuation_instruction,
                        )

        return None

    def _build_resurrection_prompt(
        self,
        project_name: str,
        workspace_path: str,
        task_title: str,
        session_title: str,
        checkpoint_summary: str,
        message_count: int,
        continuation_instruction: str | None,
    ) -> str:
        """Constructs high-fidelity continuation prompt preamble."""
        lines: list[str] = [
            f"# Historical Agent Resurrection: {session_title}",
            f"- Project: {project_name} (Workspace: {workspace_path})",
            f"- Task Context: {task_title}",
            f"- Restored Conversation Turns: {message_count}",
        ]
        if checkpoint_summary:
            lines.append(f"- Prior State Summary: {checkpoint_summary}")

        if continuation_instruction:
            lines.append(f"\n## New Continuation Instruction:\n{continuation_instruction}")
        else:
            lines.append("\n## Agent Status: Ready to resume execution from breakpoint.")

        return "\n".join(lines)

    def _create_fallback_project(self, project_id: str = "unknown_proj") -> ProjectNode:
        return ProjectNode(
            project_id=project_id,
            name="Unknown Project",
            description="",
            workspace_path="/workspace",
        )

    def _create_fallback_task(
        self,
        task_id: str = "unknown_task",
        project_id: str = "unknown_proj",
    ) -> TaskNode:
        return TaskNode(
            task_id=task_id,
            project_id=project_id,
            title="Unknown Task",
            description="",
        )

    def _create_fallback_session(self, session_id: str) -> ArchivedSessionNode:
        return ArchivedSessionNode(
            session_id=session_id,
            task_id="unknown_task",
            project_id="unknown_proj",
            title="Unknown Session",
            description="",
            agent_model="default",
            status="aborted",
        )
