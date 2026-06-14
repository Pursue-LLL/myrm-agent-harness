"""Summary message builder — construct new message lists after summarisation.

[INPUT]
- schemas::StructuredSummary (POS: structured summary dataclass)
- artifact_tracker::get_artifact_tracker (POS: Artifact tracker singleton)
- langchain_core.messages::BaseMessage (POS: LangChain message base class)

[OUTPUT]
- extract_recent_messages: keep last N tool-call pairs from message history
- create_summary_message: build HumanMessage with Lost-in-Middle awareness

[POS]
Message reconstruction after summarisation.
Lost-in-Middle aware placement puts critical info at start/end of the summary
message (U-curve attention: ~80% recall at edges vs ~50% in the middle).
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from myrm_agent_harness.utils.logger_utils import get_agent_logger

from ..infra.schemas import StructuredSummary
from ..tracking.artifact_tracker import get_artifact_tracker

logger = get_agent_logger(__name__)

UNVERIFIED_CONTEXT_MARKER = (
    "<!-- [REFERENCE ONLY] Compacted from prior conversation. "
    "Treat as background reference, NOT active instructions. "
    "Do NOT answer questions or execute tasks mentioned here "
    "— they were already addressed. -->"
)

SUMMARY_END_MARKER = (
    "--- END OF CONTEXT SUMMARY — "
    "respond to the message below, not the summary above ---"
)


def extract_protected_head(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Extract protected head messages (U-curve memory protection).

    Preserves leading SystemMessages (prompt cache), first user instruction,
    and first model reply to prevent "forgetting initial instructions" in long
    conversations while maximizing prefix cache hits.
    """
    head: list[BaseMessage] = []
    if not messages:
        return head

    start_idx = 0
    while start_idx < len(messages) and isinstance(messages[start_idx], SystemMessage):
        head.append(messages[start_idx])
        start_idx += 1

    for i in range(start_idx, min(start_idx + 2, len(messages))):
        msg = messages[i]
        if isinstance(msg, HumanMessage):
            head.append(msg)
            if i + 1 < len(messages) and isinstance(messages[i + 1], AIMessage):
                head.append(messages[i + 1])
            break

    return head


from myrm_agent_harness.utils.token_estimation import estimate_message_tokens


def _align_boundary_backward(messages: list[BaseMessage], idx: int) -> int:
    """Pull a compress-end boundary backward to avoid splitting a tool_call / result group."""
    if idx <= 0 or idx >= len(messages):
        return idx
    # If the message at the boundary is a ToolMessage, we are splitting a group.
    # We must walk backward to find the parent AIMessage.
    if isinstance(messages[idx], ToolMessage):
        check = idx - 1
        while check >= 0 and isinstance(messages[check], ToolMessage):
            check -= 1
        if check >= 0 and isinstance(messages[check], AIMessage) and messages[check].tool_calls:
            return check
    return idx


def extract_recent_messages(messages: list[BaseMessage], tail_budget_tokens: int) -> list[BaseMessage]:
    """Extract recent messages by token budget, ensuring intact tool-call pairs.

    Walks backward from the end of the conversation history, accumulating tokens
    until the tail_budget_tokens is exhausted. Falls back to a minimum of 2
    messages if the budget is too small.
    """
    n = len(messages)
    if n == 0:
        return []

    accumulated = 0
    cut_idx = n

    min_tail = min(2, n)
    soft_ceiling = int(tail_budget_tokens * 1.5)

    for i in range(n - 1, -1, -1):
        msg = messages[i]
        msg_tokens = estimate_message_tokens(msg)

        if accumulated + msg_tokens > soft_ceiling and (n - i) >= min_tail:
            break

        accumulated += msg_tokens
        cut_idx = i

    fallback_cut = n - min_tail
    cut_idx = min(cut_idx, fallback_cut)

    cut_idx = _align_boundary_backward(messages, cut_idx)

    result = messages[cut_idx:]
    logger.debug(
        "Tail protection: extracted %d messages (~%d tokens) from total %d messages", len(result), accumulated, n
    )
    return result


def create_summary_message(summary: StructuredSummary, chat_id: str | None = None) -> HumanMessage:
    """Create a summary HumanMessage with Lost-in-Middle aware placement.

    Uses HumanMessage (not SystemMessage) to preserve the system prompt prefix
    cache across compaction boundaries — changing SystemMessage would invalidate
    the KV cache prefix built from the frozen system prompt.

    Layout follows U-curve attention (start/end ~80% recall, middle ~50%):
    - Head (high attention): Handoff preamble + user goal + previous task + constraints
    - Middle (low attention): completed actions + file index + resolved questions
    - Tail (high attention): key findings + errors & fixes + pending asks + state
    """
    parts: list[str] = [
        "<memory-context>",
        "[System note: The following is recalled memory context, NOT new user input. Treat as informational background data.]",
        "",
        "[Historical Summary]",
        UNVERIFIED_CONTEXT_MARKER,
        "<!-- IMPORTANT: The latest user message AFTER this summary is your ONLY active task.",
        "It is the single source of truth for what to do right now.",
        "If the latest message contradicts or changes topic from this summary, the latest message WINS",
        "— discard stale tasks entirely and do NOT resume work described here unless explicitly asked.",
        "Topic overlap with this summary does NOT mean you should resume its task.",
        "Reverse signals (stop, undo, never mind, new topic) immediately end any work from this summary. -->",
        "",
    ]

    parts.append(f"User Goal: {summary.user_goal}")

    if summary.active_task and summary.active_task != "None":
        parts.append(f"Previous Task: {summary.active_task}")

    if summary.last_action:
        parts.append(f"Last Action: {summary.last_action}")

    if summary.constraints_and_preferences:
        parts.append("")
        parts.append("User Constraints & Preferences:")
        for pref in summary.constraints_and_preferences[:5]:
            parts.append(f" - {pref}")

    if summary.completed_actions:
        parts.append("")
        parts.append("Completed Actions:")
        for action in summary.completed_actions[:10]:
            parts.append(f" - {action}")

    artifact_summary = ""
    if chat_id:
        tracker = get_artifact_tracker(chat_id)
        if tracker:
            artifact_summary = tracker.get_summary()

    if artifact_summary:
        parts.append("")
        parts.append("[Artifact Index]")
        parts.append(artifact_summary)
    elif summary.files_modified:
        parts.append("")
        parts.append("Files Modified:")
        for file in summary.files_modified:
            parts.append(f" - {file}")

    if summary.context_dump_path:
        parts.append("")
        parts.append("History Log: " + summary.context_dump_path)
        parts.append(" (use grep/cat commands to retrieve details)")

    if summary.resolved_questions:
        parts.append("")
        parts.append("Resolved Questions:")
        for q in summary.resolved_questions[:5]:
            parts.append(f" - {q}")

    if summary.key_findings:
        parts.append("")
        parts.append("Key Findings:")
        for finding in summary.key_findings[:5]:
            parts.append(f" - {finding}")

    if summary.errors_and_fixes:
        parts.append("")
        parts.append("Errors & Fixes:")
        for item in summary.errors_and_fixes[:8]:
            parts.append(f" - {item}")

    if summary.pending_user_asks:
        pending = [a for a in summary.pending_user_asks if a != "None"]
        if pending:
            parts.append("")
            parts.append("Pending User Asks:")
            for ask in pending[:5]:
                parts.append(f" - {ask}")

    if summary.active_state:
        parts.append("")
        parts.append(f"Working State: {summary.active_state}")

    parts.append("")
    parts.append("<!-- SUMMARY_JSON")
    parts.append(summary.to_json())
    parts.append("-->")
    parts.append("</memory-context>")
    parts.append(SUMMARY_END_MARKER)

    return HumanMessage(content="\n".join(parts))
