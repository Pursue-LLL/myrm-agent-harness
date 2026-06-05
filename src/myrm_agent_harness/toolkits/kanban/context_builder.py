"""Worker context builder for kanban task execution.

Assembles a structured text context for task runners, including:
- Task info (title, description, status, priority)
- Prior attempt history (summary, error per run)
- Parent task results and handoff metadata (from dependency chain)
- User comments (from event timeline)
- Multimodal query construction for tasks with attachments

[INPUT]
- .protocols::KanbanStore (POS: Data access for tasks, runs, events, dependencies.)

[OUTPUT]
- build_task_context: async function returning assembled context string.
- build_multimodal_query: pure function assembling text + attachments into LLM content blocks.

[POS]
Kanban worker context assembly helper for TaskRunner implementors.
"""

from __future__ import annotations

import json

from myrm_agent_harness.toolkits.kanban.protocols import KanbanStore
from myrm_agent_harness.toolkits.kanban.types import TaskAttachment, TaskEventKind

_CTX_MAX_PRIOR_ATTEMPTS = 5
_CTX_MAX_COMMENTS = 20
_CTX_MAX_FIELD_CHARS = 4000


def _cap(text: str | None, limit: int = _CTX_MAX_FIELD_CHARS) -> str:
    if not text:
        return ""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + f"… [{len(text) - limit} chars omitted]"


async def build_task_context(store: KanbanStore, task_id: str) -> str:
    """Assemble full worker context for a kanban task.

    Designed for TaskRunner implementations to call before executing a task,
    providing the runner with all necessary context: task details, prior
    attempt history, parent task results (including handoff metadata), and
    user comments.
    """
    task = await store.get_task(task_id)
    if task is None:
        raise ValueError(f"Unknown task {task_id}")

    lines: list[str] = []

    lines.append(f"# Task: {task.title}")
    lines.append(f"Status: {task.status.value} | Priority: {task.priority.value}")
    if task.agent_id:
        lines.append(f"Assigned agent: {task.agent_id}")
    lines.append("")

    if task.description:
        lines.append("## Description")
        lines.append(_cap(task.description, 8000))
        lines.append("")

    runs = await store.list_runs(task_id)
    finished_runs = [r for r in runs if r.is_finished]
    if finished_runs:
        if len(finished_runs) > _CTX_MAX_PRIOR_ATTEMPTS:
            omitted = len(finished_runs) - _CTX_MAX_PRIOR_ATTEMPTS
            shown = finished_runs[-_CTX_MAX_PRIOR_ATTEMPTS:]
        else:
            omitted = 0
            shown = finished_runs

        lines.append("## Prior attempts")
        if omitted:
            lines.append(f"({omitted} earlier attempts omitted)")
        for i, run in enumerate(shown, 1):
            outcome = run.outcome.value if run.outcome else "unknown"
            duration = f"{run.duration_seconds:.1f}s" if run.duration_seconds else "-"
            lines.append(f"### Attempt {i} — {outcome} ({duration})")
            if run.summary:
                lines.append(_cap(run.summary))
            if run.error:
                lines.append(f"Error: {_cap(run.error)}")
            lines.append("")

    parent_ids = await store.list_parents(task_id)
    if parent_ids:
        parent_results: list[str] = []
        for pid in parent_ids:
            parent = await store.get_task(pid)
            if parent is None or not parent.is_terminal:
                continue
            parent_lines = [f"### {parent.title} ({parent.status.value})"]
            if parent.result:
                parent_lines.append(_cap(parent.result))
            else:
                parent_lines.append("(no result recorded)")
            handoff = parent.metadata.get("handoff") if parent.metadata else None
            if handoff and isinstance(handoff, dict):
                parent_lines.append(f"Handoff: {_cap(json.dumps(handoff, ensure_ascii=False))}")
            parent_results.extend(parent_lines)
            parent_results.append("")

        if parent_results:
            lines.append("## Parent task results")
            lines.extend(parent_results)

    events = await store.list_events(task_id)
    comments = [e for e in events if e.kind == TaskEventKind.USER_COMMENT and e.payload]
    if comments:
        if len(comments) > _CTX_MAX_COMMENTS:
            omitted_c = len(comments) - _CTX_MAX_COMMENTS
            shown_c = comments[-_CTX_MAX_COMMENTS:]
        else:
            omitted_c = 0
            shown_c = comments

        lines.append("## Comments")
        if omitted_c:
            lines.append(f"({omitted_c} earlier comments omitted)")
        for c in shown_c:
            author = c.payload.get("author", "user") if c.payload else "user"
            body = c.payload.get("body", "") if c.payload else ""
            ts = c.created_at.strftime("%Y-%m-%d %H:%M")
            lines.append(f"@{author} ({ts}): {_cap(str(body), 2000)}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Multimodal query assembly
# ---------------------------------------------------------------------------

_IMAGE_MIME_PREFIXES = ("image/",)


def build_multimodal_query(
    text_context: str,
    attachments: list[TaskAttachment],
    *,
    has_vision: bool = True,
) -> str | list[dict[str, object]]:
    """Assemble text context + attachments into an LLM-ready query.

    Pure function — no I/O. Returns plain str when no visual attachments are
    present (zero overhead for text-only tasks). When images exist and the model
    supports vision, returns OpenAI-compatible multimodal content blocks.

    For non-vision models (has_vision=False), image attachments degrade to
    text hints so the agent is aware they exist and can request alternatives.
    """
    if not attachments:
        return text_context

    image_attachments = [a for a in attachments if a.mime_type.startswith(_IMAGE_MIME_PREFIXES)]
    doc_attachments = [a for a in attachments if not a.mime_type.startswith(_IMAGE_MIME_PREFIXES)]

    if not image_attachments and not doc_attachments:
        return text_context

    blocks: list[dict[str, object]] = [{"type": "text", "text": text_context}]

    for att in image_attachments:
        if has_vision:
            blocks.append(
                {
                    "type": "image_url",
                    "image_url": {"url": att.content_ref},
                }
            )
        else:
            blocks.append(
                {
                    "type": "text",
                    "text": f"[Attached image: {att.filename} ({att.size_bytes / 1024:.0f}KB) — model lacks vision, describe or switch model]",
                }
            )

    for att in doc_attachments:
        blocks.append(
            {
                "type": "text",
                "text": f"[Attached file: {att.filename} ({att.size_bytes / 1024:.0f}KB, {att.mime_type}) ref={att.content_ref}]",
            }
        )

    return blocks
