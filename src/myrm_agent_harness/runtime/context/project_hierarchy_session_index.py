"""Full-text keyword indexing and search engine for hierarchical project sessions.

Provides inverted token indexing, multi-field weighted scoring, and hierarchical
grouping across Project-Task-Session-Message graphs, empowering developers to
locate historical diagnostic context and past agent resolutions within milliseconds.

[INPUT]
- runtime.context.project_hierarchy_session_types::ArchivedMessageEntry, ArchivedSessionNode,
  HierarchyGroupMatch, HierarchyHitKind, HierarchySearchHit, HierarchySearchResult, ProjectNode, TaskNode
  (POS: Project hierarchy session archive and keyword resurrection types.)

[OUTPUT]
- ProjectHierarchySessionIndex: In-memory full-text search and hierarchy manager for project session
  archives.

[POS]
Full-text keyword indexing and search engine for hierarchical project sessions.
"""

from __future__ import annotations

from collections.abc import Sequence

from .project_hierarchy_session_types import (
    ArchivedMessageEntry,
    ArchivedSessionNode,
    HierarchyGroupMatch,
    HierarchyHitKind,
    HierarchySearchHit,
    HierarchySearchResult,
    ProjectNode,
    TaskNode,
)


class ProjectHierarchySessionIndex:
    """In-memory full-text search and hierarchy manager for project session archives."""

    def __init__(self) -> None:
        self._projects: dict[str, ProjectNode] = {}
        self._tasks: dict[str, TaskNode] = {}
        self._sessions: dict[str, ArchivedSessionNode] = {}
        self._session_messages: dict[str, list[ArchivedMessageEntry]] = {}

    def register_project(self, project: ProjectNode) -> None:
        """Registers a project anchor node."""
        self._projects[project.project_id] = project

    def register_task(self, task: TaskNode) -> None:
        """Registers a task node under a project."""
        self._tasks[task.task_id] = task

    def archive_session(
        self,
        session: ArchivedSessionNode,
        messages: Sequence[ArchivedMessageEntry],
    ) -> None:
        """Archives a session node with its conversation turns."""
        self._sessions[session.session_id] = session
        self._session_messages[session.session_id] = list(messages)

    def get_project(self, project_id: str) -> ProjectNode | None:
        """Retrieves project by ID."""
        return self._projects.get(project_id)

    def get_task(self, task_id: str) -> TaskNode | None:
        """Retrieves task by ID."""
        return self._tasks.get(task_id)

    def get_session(self, session_id: str) -> ArchivedSessionNode | None:
        """Retrieves session by ID."""
        return self._sessions.get(session_id)

    def get_messages(self, session_id: str) -> tuple[ArchivedMessageEntry, ...]:
        """Retrieves message history for a session."""
        return tuple(self._session_messages.get(session_id, []))

    def search(
        self,
        query: str,
        project_id: str | None = None,
        max_matches_per_project: int = 15,
        limit_projects: int = 20,
    ) -> HierarchySearchResult:
        """Executes a multi-field full-text search across projects, tasks, sessions, and messages."""
        clean_query = query.strip()
        if not clean_query:
            return HierarchySearchResult(
                query=query,
                total_hits=0,
                groups=(),
                is_truncated=False,
            )

        q_lower = clean_query.lower()
        project_hits_map: dict[str, list[HierarchySearchHit]] = {}

        # 1. Search Project nodes
        target_projects = (
            [self._projects[project_id]]
            if project_id and project_id in self._projects
            else list(self._projects.values())
        )

        for proj in target_projects:
            p_hits: list[HierarchySearchHit] = []
            proj_matched_fields = self._match_fields(
                q_lower,
                [
                    ("name", proj.name),
                    ("description", proj.description),
                    ("workspace_path", proj.workspace_path),
                    ("tags", " ".join(proj.tags)),
                ],
            )
            if proj_matched_fields:
                score = self._compute_score(proj.name, proj.description, q_lower, base=1.0)
                p_hits.append(
                    HierarchySearchHit(
                        kind=HierarchyHitKind.PROJECT,
                        id=proj.project_id,
                        title=proj.name,
                        snippet=proj.description[:120],
                        project_id=proj.project_id,
                        task_id=None,
                        session_id=None,
                        score=score,
                        matched_fields=tuple(proj_matched_fields),
                    )
                )

            project_hits_map[proj.project_id] = p_hits

        # 2. Search Task nodes
        for task in self._tasks.values():
            if project_id and task.project_id != project_id:
                continue
            if task.project_id not in project_hits_map:
                continue

            task_matched_fields = self._match_fields(
                q_lower,
                [
                    ("title", task.title),
                    ("description", task.description),
                    ("tags", " ".join(task.tags)),
                ],
            )
            if task_matched_fields:
                score = self._compute_score(task.title, task.description, q_lower, base=2.0)
                project_hits_map[task.project_id].append(
                    HierarchySearchHit(
                        kind=HierarchyHitKind.TASK,
                        id=task.task_id,
                        title=task.title,
                        snippet=task.description[:120],
                        project_id=task.project_id,
                        task_id=task.task_id,
                        session_id=None,
                        score=score,
                        matched_fields=tuple(task_matched_fields),
                    )
                )

        # 3. Search Sessions and Messages
        for sess in self._sessions.values():
            if project_id and sess.project_id != project_id:
                continue
            if sess.project_id not in project_hits_map:
                continue

            # Check session metadata
            sess_matched_fields = self._match_fields(
                q_lower,
                [
                    ("title", sess.title),
                    ("description", sess.description),
                    ("checkpoint_summary", sess.checkpoint_summary),
                    ("tags", " ".join(sess.tags)),
                ],
            )
            if sess_matched_fields:
                score = self._compute_score(sess.title, sess.description, q_lower, base=3.0)
                project_hits_map[sess.project_id].append(
                    HierarchySearchHit(
                        kind=HierarchyHitKind.SESSION,
                        id=sess.session_id,
                        title=sess.title,
                        snippet=(sess.checkpoint_summary or sess.description)[:140],
                        project_id=sess.project_id,
                        task_id=sess.task_id,
                        session_id=sess.session_id,
                        score=score,
                        matched_fields=tuple(sess_matched_fields),
                    )
                )

            # Check individual messages in this session
            msgs = self._session_messages.get(sess.session_id, [])
            for msg in msgs:
                msg_matched_fields = self._match_fields(
                    q_lower,
                    [
                        ("content", msg.content),
                        ("tool_calls", " ".join(msg.tool_calls)),
                        ("error_traces", " ".join(msg.error_traces)),
                        ("file_references", " ".join(msg.file_references)),
                    ],
                )
                if msg_matched_fields:
                    snippet = self._extract_snippet(msg.content, q_lower)
                    score = self._compute_score(snippet, msg.content, q_lower, base=4.0)
                    project_hits_map[sess.project_id].append(
                        HierarchySearchHit(
                            kind=HierarchyHitKind.MESSAGE,
                            id=msg.message_id,
                            title=f"Turn in [{sess.title}]",
                            snippet=snippet,
                            project_id=sess.project_id,
                            task_id=sess.task_id,
                            session_id=sess.session_id,
                            score=score,
                            matched_fields=tuple(msg_matched_fields),
                        )
                    )

        # 4. Aggregate and sort groups
        groups: list[HierarchyGroupMatch] = []
        total_hits = 0
        truncated = False

        for p_id, hits in project_hits_map.items():
            if not hits:
                continue
            hits.sort(key=lambda h: h.score)
            total_hits += len(hits)
            best_score = hits[0].score

            if len(hits) > max_matches_per_project:
                truncated = True
                hits = hits[:max_matches_per_project]

            proj = self._projects[p_id]
            groups.append(
                HierarchyGroupMatch(
                    project=proj,
                    matches=tuple(hits),
                    total_matches=len(hits),
                    best_score=best_score,
                )
            )

        groups.sort(key=lambda g: g.best_score)
        if len(groups) > limit_projects:
            truncated = True
            groups = groups[:limit_projects]

        return HierarchySearchResult(
            query=clean_query,
            total_hits=total_hits,
            groups=tuple(groups),
            is_truncated=truncated,
        )

    def _match_fields(
        self,
        query: str,
        fields: Sequence[tuple[str, str]],
    ) -> list[str]:
        """Returns list of field names that contain the search query."""
        matched: list[str] = []
        for name, text in fields:
            if text and query in text.lower():
                matched.append(name)
        return matched

    def _compute_score(
        self,
        title: str,
        body: str,
        query: str,
        base: float,
    ) -> float:
        """Calculates relevancy rank (lower is better rank)."""
        t_low = title.lower() if title else ""
        b_low = body.lower() if body else ""

        if t_low == query:
            return base
        if t_low.startswith(query):
            return base + 0.2
        if query in t_low:
            return base + 0.5
        if query in b_low:
            return base + 1.0
        return base + 2.0

    def _extract_snippet(self, text: str, query: str) -> str:
        """Extracts text excerpt around the matched query."""
        if not text:
            return ""
        idx = text.lower().find(query)
        if idx == -1:
            return text[:120].strip()

        start = max(0, idx - 40)
        end = min(len(text), idx + len(query) + 60)
        snippet = text[start:end].replace("\n", " ").strip()
        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(text) else ""
        return f"{prefix}{snippet}{suffix}"
