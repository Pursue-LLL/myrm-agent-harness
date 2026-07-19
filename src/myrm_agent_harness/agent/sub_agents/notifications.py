"""Push-based notification formatting for subagent completion events.

SubagentManager queues formatted completion text via ``NotificationManager``.
``StreamRecoveryContinuation`` drains notifications and emits SSE only (no message injection).
Background async wakeup appends user/HumanMessage via ``ServerWakeupHandler`` (server layer).

[INPUT]
- (none)

[OUTPUT]
- SubagentNotification: Push notification from a completed child agent to the parent.
- NotificationManager: Manages pending notifications from subagents to the parent agent.
- format_notification: Format a SubAgentResult into a notification for the parent LLM.
- format_active_subagent_context: Format currently running subagents into a context snippet for the parent LLM.

[POS]
Push-based notification formatting for subagent completion events and active subagent context injection.
"""

import time
from collections import deque
from dataclasses import dataclass

from myrm_agent_harness.agent.sub_agents.types import SubAgentResult
from myrm_agent_harness.utils.logger_utils import get_agent_logger

_NOTIFICATION_TTL_SECONDS = 300.0
_FALLBACK_MAX_ERROR_CHARS = 2000
logger = get_agent_logger(__name__)


@dataclass(frozen=True, slots=True)
class SubagentNotification:
    """Push notification from a completed child agent to the parent."""

    content: str
    timestamp: float


def format_notification(result: SubAgentResult) -> str:
    """Format a SubAgentResult into a notification for the parent LLM.

    Includes result summary and a behavioural instruction so the parent knows
    to process the result instead of polling.
    """
    status_text = "completed successfully" if result.success else "failed"
    parts = [f"[Subagent '{result.agent_type}' (task_id={result.task_id}) {status_text}]"]
    if result.duration_seconds:
        parts[0] += f" ({result.duration_seconds:.1f}s)"
    if result.success and result.result:
        parts.append(f"Result:\n{result.result}")
    elif result.error:
        from myrm_agent_harness.agent.sub_agents.executor import _compact_error_message

        parts.append(f"Error: {_compact_error_message(result.error, _FALLBACK_MAX_ERROR_CHARS)}")
    if result.handover_state:
        ho = result.handover_state
        ho_lines: list[str] = []
        if ho.task_completed:
            ho_lines.append("Completed:\n" + "\n".join(f" - {x}" for x in ho.task_completed))
        if ho.pending_todos:
            ho_lines.append("Pending:\n" + "\n".join(f" - {x}" for x in ho.pending_todos))
        if ho.risks_or_notes:
            ho_lines.append("Risks:\n" + "\n".join(f" - {x}" for x in ho.risks_or_notes))
        if ho_lines:
            parts.append("Handover:\n" + "\n".join(ho_lines))
    parts.append(
        "Process this result and continue your workflow. "
        "If all async tasks are done, provide the final answer to the user."
    )
    return "\n".join(parts)


def format_active_subagent_context(children: list[dict[str, object]]) -> str | None:
    """Format currently running subagents into a context snippet for the parent LLM.

    Filters ``children`` (from ``SubagentManager.list_children()``) to only
    running entries and produces a compact summary with anti-duplicate-spawn
    guidance.  Returns ``None`` when no subagents are running.
    """
    running = [c for c in children if c.get("status") == "running" and not c.get("done")]
    if not running:
        return None

    lines = ["[Active subagents]"]
    for child in running:
        task_id = child.get("task_id", "?")
        agent_type = child.get("agent_type", "unknown")
        desc = child.get("description", "")
        entry = f"- {agent_type} (task_id={task_id})"
        if desc:
            entry += f": {desc}"
        lines.append(entry)

    lines.append(
        "These tasks are still running. "
        "Do NOT spawn duplicate tasks for the same purpose. "
        "Use subagent_control_tool with action=list to check their results when needed."
    )
    return "\n".join(lines)


class NotificationManager:
    """Manages pending notifications from subagents to the parent agent."""

    __slots__ = "_pending_notifications"

    def __init__(self) -> None:
        self._pending_notifications: deque[SubagentNotification] = deque()

    def add_notification(self, result: SubAgentResult, timestamp: float) -> None:
        """Add a completion notification to the queue."""
        content = format_notification(result)
        self._pending_notifications.append(SubagentNotification(content=content, timestamp=timestamp))
        logger.debug("[subagent:%s] Pushed completion notification to parent", result.task_id)

    def drain_notifications(self) -> str | None:
        """Drain all pending completion notifications, merging into a single text.

        Notifications older than ``_NOTIFICATION_TTL_SECONDS`` are silently discarded.
        Returns ``None`` if no fresh notifications are available.
        """
        if not self._pending_notifications:
            return None

        now = time.time()
        fresh: list[str] = []
        while self._pending_notifications:
            notif = self._pending_notifications.popleft()
            if (now - notif.timestamp) <= _NOTIFICATION_TTL_SECONDS:
                fresh.append(notif.content)

        if not fresh:
            return None

        logger.info("Draining %d subagent notification(s) into parent context", len(fresh))
        return "\n\n---\n\n".join(fresh)
