"""Session Notes pipeline processor.

Inserted between CompressProcessor and SummarizeProcessor. When notes are ready,
directly builds a summary message from notes to replace old messages (zero API calls).
When notes are not ready, passes through to SummarizeProcessor (natural degradation).

Pipeline order: Filter -> Compress -> **SessionNotesProcessor** -> Summarize -> ExplicitCache

[INPUT]
- (none)

[OUTPUT]
- SessionNotesProcessor: class — Session Notes Processor

[POS]
Provides SessionNotesProcessor.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.token_estimation import estimate_messages_tokens

from ...strategies.summary_builder import UNVERIFIED_CONTEXT_MARKER
from ..base import BaseProcessor, ProcessorContext

if TYPE_CHECKING:
    from ...infra.schemas import StructuredSummary
    from ...strategies.session_notes.schemas import SessionNotes
    from ...strategies.session_notes.updater import SessionNotesManager

logger = get_agent_logger(__name__)

MIN_KEEP_TOKENS = 10_000
MIN_KEEP_TEXT_MESSAGES = 5
MAX_KEEP_TOKENS = 40_000


class SessionNotesProcessor(BaseProcessor):
    """Session Notes processor.

    When notes are ready and context needs compression:
    1. Wait for in-progress notes update to complete
    2. Build summary message from notes
    3. Keep recent messages (multi-dimensional strategy)
    4. Replace old messages; reduced token count prevents SummarizeProcessor from triggering
    """

    def __init__(self, manager: SessionNotesManager, summarize_trigger_threshold: int = 115200) -> None:
        self._manager = manager
        self._summarize_trigger_threshold = summarize_trigger_threshold

    @property
    def name(self) -> str:
        return "session_notes"

    async def should_process(self, context: ProcessorContext) -> bool:
        total_tokens = estimate_messages_tokens(context.messages)
        if total_tokens < self._summarize_trigger_threshold:
            return False
        return self._manager.notes.is_ready()

    async def process(self, context: ProcessorContext) -> ProcessorContext:
        # Prompt Cache preservation: Skip SessionNotes during Resume or HITL session
        if self._should_skip_for_cache_preservation(context):
            logger.info(
                "[SessionNotes] Skipped for Prompt Cache preservation (is_resume=%s, hitl_session_active=%s)",
                context.is_resume,
                context.merged_context.get("hitl_session_active"),
            )
            return context

        await self._manager.wait_for_update()

        notes = self._manager.notes
        if not notes.is_ready():
            logger.warning("[SessionNotes] Notes not ready after wait, falling through to Summarize")
            return context

        original_tokens = estimate_messages_tokens(context.messages)

        summary_text, was_truncated = notes.truncate_for_compact()
        if was_truncated:
            logger.info("[SessionNotes] Some sections were truncated for length")

        summary_message = HumanMessage(
            content=(
                f"[System note: Session Notes Summary — not user input]\n{UNVERIFIED_CONTEXT_MARKER}\n\n{summary_text}"
            )
        )

        from ...strategies.pre_compact_context import prepend_pre_compact_message
        from ...strategies.summary_builder import extract_protected_head

        protected_head = extract_protected_head(context.messages)
        keep_start = _calculate_keep_index(context.messages, notes.last_updated_message_idx)

        # Ensure recent messages do not overlap with protected head
        keep_start = max(keep_start, len(protected_head))

        recent_messages = context.messages[keep_start:]

        context.messages = prepend_pre_compact_message(
            protected_head,
            [summary_message],
            recent_messages,
            context=context,
        )

        new_tokens = estimate_messages_tokens(context.messages)
        saved = original_tokens - new_tokens
        context.tokens_saved += saved

        context.structured_summary = _build_structured_summary(notes)

        from ...infra.cache_break_detector import get_cache_break_detector

        detector = get_cache_break_detector()
        if detector is not None:
            detector.notify_compaction()

        logger.info(
            "[SessionNotes] Compacted with notes: %d -> %d tokens (saved %d) | zero API calls",
            original_tokens,
            new_tokens,
            saved,
        )

        return context


def _calculate_keep_index(messages: list[BaseMessage], last_summarized_idx: int) -> int:
    """Calculate keep-start index for recent messages (multi-dimensional strategy).

    Inspired by Claude Code's calculateMessagesToKeepIndex:
    - Start from last_summarized_idx + 1
    - Expand backwards until minTokens + minTextMessages are met or maxTokens reached
    - Ensure tool_use/tool_result pairs are not split
    - Anchor: the last HumanMessage is always in the kept region
    """
    if not messages:
        return 0

    start = min(last_summarized_idx + 1, len(messages))

    total_tokens = 0
    text_message_count = 0
    for i in range(start, len(messages)):
        total_tokens += _estimate_single_message_tokens(messages[i])
        if _has_text_content(messages[i]):
            text_message_count += 1

    if total_tokens >= MAX_KEEP_TOKENS:
        start = _adjust_for_tool_pairs(messages, start)
        return _anchor_last_user_message(messages, start)

    if total_tokens >= MIN_KEEP_TOKENS and text_message_count >= MIN_KEEP_TEXT_MESSAGES:
        start = _adjust_for_tool_pairs(messages, start)
        return _anchor_last_user_message(messages, start)

    for i in range(start - 1, -1, -1):
        msg_tokens = _estimate_single_message_tokens(messages[i])
        total_tokens += msg_tokens
        if _has_text_content(messages[i]):
            text_message_count += 1
        start = i

        if total_tokens >= MAX_KEEP_TOKENS:
            break
        if total_tokens >= MIN_KEEP_TOKENS and text_message_count >= MIN_KEEP_TEXT_MESSAGES:
            break

    start = _adjust_for_tool_pairs(messages, start)
    return _anchor_last_user_message(messages, start)


def _anchor_last_user_message(messages: list[BaseMessage], start: int) -> int:
    """Ensure the last HumanMessage is in the kept region (messages[start:]).

    Prevents active-task loss after compression when large tool results push
    the keep boundary past the user's latest instruction.
    """
    for idx in range(len(messages) - 1, -1, -1):
        if isinstance(messages[idx], HumanMessage):
            if idx < start:
                logger.debug(
                    "Anchored last user message (idx=%d) into kept region (was %d)",
                    idx,
                    start,
                )
                return idx
            return start
    return start


def _adjust_for_tool_pairs(messages: list[BaseMessage], start_index: int) -> int:
    """Adjust start index to avoid splitting tool_use/tool_result pairs."""
    if start_index <= 0 or start_index >= len(messages):
        return start_index

    tool_result_ids: set[str] = set()
    for i in range(start_index, len(messages)):
        msg = messages[i]
        if isinstance(msg, ToolMessage) and hasattr(msg, "tool_call_id"):
            tool_result_ids.add(msg.tool_call_id)

    if not tool_result_ids:
        return start_index

    kept_tool_use_ids: set[str] = set()
    for i in range(start_index, len(messages)):
        msg = messages[i]
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                kept_tool_use_ids.add(tc["id"])

    needed = tool_result_ids - kept_tool_use_ids
    if not needed:
        return start_index

    adjusted = start_index
    for i in range(start_index - 1, -1, -1):
        msg = messages[i]
        if isinstance(msg, AIMessage) and msg.tool_calls:
            found_ids = {tc["id"] for tc in msg.tool_calls}
            if found_ids & needed:
                adjusted = i
                needed -= found_ids
                if not needed:
                    break

    return adjusted


def _has_text_content(msg: BaseMessage) -> bool:
    """Check whether a message contains text content."""
    if isinstance(msg, (HumanMessage, SystemMessage)):
        return bool(msg.content)
    if isinstance(msg, AIMessage):
        if isinstance(msg.content, str):
            return bool(msg.content.strip())
        if isinstance(msg.content, list):
            return any(isinstance(block, dict) and block.get("type") == "text" for block in msg.content)
    return False


def _estimate_single_message_tokens(msg: BaseMessage) -> int:
    """Estimate token count for a single message."""
    return estimate_messages_tokens([msg])


def _build_structured_summary(notes: SessionNotes) -> StructuredSummary:
    """Build StructuredSummary from SessionNotes (for persistence bridging)."""
    from ...infra.schemas import StructuredSummary

    task_spec = notes.get_section("task_spec")
    current_state = notes.get_section("current_state")
    worklog = notes.get_section("worklog")
    findings = notes.get_section("key_findings")
    files = notes.get_section("files_and_functions")
    errors = notes.get_section("errors_and_corrections")

    completed_actions = _extract_lines(worklog.content, max_items=10) if worklog else []
    key_findings_list = _extract_lines(findings.content, max_items=8) if findings else []
    files_modified = _extract_lines(files.content, max_items=15) if files else []
    errors_and_fixes = _extract_lines(errors.content, max_items=8) if errors else []

    return StructuredSummary(
        user_goal=task_spec.content[:300] if task_spec else "",
        completed_actions=completed_actions,
        key_findings=key_findings_list,
        errors_and_fixes=errors_and_fixes,
        files_modified=files_modified,
        last_action=current_state.content[:300] if current_state else "",
        active_state=current_state.content[:300] if current_state else "",
    )


def _extract_lines(content: str, max_items: int = 10) -> list[str]:
    """Extract line list from section content (strip empty lines and markdown markers)."""
    lines: list[str] = []
    for line in content.strip().splitlines():
        stripped = line.strip().lstrip("-•*").strip()
        if stripped:
            lines.append(stripped[:200])
            if len(lines) >= max_items:
                break
    return lines
