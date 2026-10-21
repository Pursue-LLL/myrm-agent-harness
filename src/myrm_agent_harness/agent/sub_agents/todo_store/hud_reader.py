"""
[POS] myrm_agent_harness/agent/sub_agents/todo_store/hud_reader.py
[INPUT] myrm_agent_harness.agent.sub_agents.todo_store.sanitizer, myrm_agent_harness.agent.sub_agents.todo_store.store, myrm_agent_harness.agent.sub_agents.todo_store.types
[OUTPUT] SharedTodoHudReader

Read-only, terminal-escape safe HUD reader and projector for shared Todo plans.
Produces sanitized text and metrics for terminal, TUI, and WebUI HUD views.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from myrm_agent_harness.agent.sub_agents.todo_store.sanitizer import (
    strip_control_characters,
)
from myrm_agent_harness.agent.sub_agents.todo_store.store import SharedTodoStore
from myrm_agent_harness.agent.sub_agents.todo_store.types import (
    PLAN_DECLARATION_SEMANTIC_NOTE,
    TodoHudProjection,
    TodoItem,
)


class SharedTodoHudReader:
    """
    Projector that reads from a SharedTodoStore and generates safe,
    ANSI-stripped HUD projections and compact terminal lines.
    """

    def __init__(self, store: SharedTodoStore) -> None:
        self.store = store

    def project_hud(self) -> TodoHudProjection:
        """Construct a sanitized, read-only projection of the current plan state."""
        raw_items = self.store.get_items()

        # Sanitize on read
        sanitized_items: list[TodoItem] = []
        pending_count = 0
        in_progress_count = 0
        completed_count = 0
        cancelled_count = 0

        for item in raw_items:
            clean_title = strip_control_characters(item.title)
            clean_desc = strip_control_characters(item.description)
            clean_assignee = strip_control_characters(item.assignee)
            clean_item = TodoItem(
                item_id=item.item_id,
                title=clean_title,
                description=clean_desc,
                status=item.status,
                assignee=clean_assignee,
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
            sanitized_items.append(clean_item)

            if item.status == "pending":
                pending_count += 1
            elif item.status == "in_progress":
                in_progress_count += 1
            elif item.status == "completed":
                completed_count += 1
            elif item.status == "cancelled":
                cancelled_count += 1

        total_count = len(sanitized_items)
        progress_pct = (
            round((completed_count / total_count) * 100.0, 1) if total_count > 0 else 0.0
        )

        active_items = [
            i for i in sanitized_items if i.status in ("in_progress", "pending")
        ]

        # Generate formatted HUD lines
        lines: list[str] = []
        if total_count == 0:
            lines.append("[PLAN HUD] No active plan declarations.")
        else:
            lines.append(
                f"[PLAN HUD] Progress: {progress_pct:.1f}% "
                f"({completed_count}/{total_count} done, {in_progress_count} in-progress, {pending_count} pending)"
            )
            for idx, item in enumerate(sanitized_items, start=1):
                marker = "[ ]"
                if item.status == "in_progress":
                    marker = "[>]"
                elif item.status == "completed":
                    marker = "[x]"
                elif item.status == "cancelled":
                    marker = "[-]"

                assignee_badge = f" @{item.assignee}" if item.assignee else ""
                line = f"{marker} {idx}. {item.title}{assignee_badge}"
                lines.append(line)

        lines.append(f"Note: {PLAN_DECLARATION_SEMANTIC_NOTE}")

        return TodoHudProjection(
            session_id=self.store.session_id,
            total_count=total_count,
            pending_count=pending_count,
            in_progress_count=in_progress_count,
            completed_count=completed_count,
            cancelled_count=cancelled_count,
            progress_pct=progress_pct,
            active_items=active_items,
            formatted_hud_lines=lines,
            semantic_contract=PLAN_DECLARATION_SEMANTIC_NOTE,
        )

    def render_compact_text(self) -> str:
        """Render single or multi-line plain text safe for terminal HUD printing."""
        projection = self.project_hud()
        return "\n".join(projection.formatted_hud_lines)
