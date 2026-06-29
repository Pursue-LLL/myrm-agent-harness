"""Automatic first-turn session recall middleware.

Proactively injects relevant historical conversation context on the first
user turn of a new session, eliminating the need for the Agent to manually
invoke ``conversation_search`` tool.

Strategy:
1. Idempotency: Skip if recall marker already present in the message history.
2. Quick path: Skip if user has zero conversation/task_digest memories (count check).
3. Query extraction: Use the first HumanMessage as the retrieval query.
4. Short-query filter: Skip if query < 8 chars (too ambiguous for meaningful recall).
5. Parallel hybrid retrieval: RRF fusion with configurable timeout.
6. High-threshold filtering: Only inject results above configured score threshold.
7. Safe encapsulation: Wrap results with ``wrap_untrusted`` and inject as HumanMessage.

[INPUT]
- toolkits.memory.config::RecallMode (POS: Memory configuration — functional switches and retrieval params only.)
- toolkits.memory.manager::MemoryManager (POS: Unified memory manager and core facade of the Memory Toolkit.)
- agent.security.detection.content_boundary::wrap_untrusted (POS: Untrusted content folding.)
- agent._skill_agent_context::get_memory_manager (POS: ContextVar-based memory manager accessor.)

[OUTPUT]
- auto_session_recall_middleware: AgentMiddleware — first-turn historical conversation auto-injection.

[POS]
First-turn auto session recall middleware. Searches conversation/task_digest memories
and injects high-confidence results before Agent's first reasoning turn.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import BaseMessage, HumanMessage

from myrm_agent_harness.agent.security.detection.content_boundary import wrap_untrusted
from myrm_agent_harness.toolkits.memory.config import RecallMode
from myrm_agent_harness.toolkits.memory.types import MemoryType

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.manager import MemoryManager
    from myrm_agent_harness.toolkits.memory.types import MemorySearchResult

logger = logging.getLogger(__name__)

_SESSION_RECALL_MARKER = "<auto_session_recall"
_MIN_QUERY_LENGTH = 8
_MAX_RESULTS = 2
_DEFAULT_THRESHOLD = 0.72
_DEFAULT_BUDGET_TOKENS = 800
_DEFAULT_TIMEOUT = 3.0
_CHARS_PER_TOKEN = 4


def _has_session_recall(messages: Sequence[BaseMessage]) -> bool:
    """Check if auto session recall has already been injected."""
    for msg in messages[:15]:
        if isinstance(msg, HumanMessage):
            content = msg.content
            if isinstance(content, str) and _SESSION_RECALL_MARKER in content:
                return True
    return False


_UNTRUSTED_MARKER = "<<<UNTRUSTED_DATA"


def _extract_query(messages: Sequence[BaseMessage]) -> str:
    """Extract the user's first query from messages for retrieval."""
    for msg in messages:
        if isinstance(msg, HumanMessage):
            content = msg.content
            if isinstance(content, str):
                text = content.strip()
                if text and _SESSION_RECALL_MARKER not in text and _UNTRUSTED_MARKER not in text:
                    return text[:2000]
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "").strip()
                        if text and _UNTRUSTED_MARKER not in text:
                            return text[:2000]
    return ""


def _format_recall_body(results: list[MemorySearchResult], budget_tokens: int) -> str:
    """Format recalled memories into a concise injection body."""
    max_chars = budget_tokens * _CHARS_PER_TOKEN
    lines: list[str] = []
    used = 0

    for result in results:
        memory = result.memory
        content = memory.content
        if len(content) > 600:
            content = content[:597] + "..."

        line = f"- [{result.memory_type.value}] score:{result.score:.2f} | {content}"
        line_len = len(line)
        if used + line_len > max_chars:
            break
        lines.append(line)
        used += line_len

    return "\n".join(lines)


class AutoSessionRecallMiddleware(AgentMiddleware):  # type: ignore[type-arg]
    """Inject relevant historical context on first LLM call of a new session.

    Searches conversation and task_digest memories using the user's query,
    injecting high-confidence results as a HumanMessage with untrusted wrapping.
    Completely non-blocking: failures degrade gracefully to no-injection.
    """

    name = "auto_session_recall_middleware"

    async def awrap_model_call(
        self, request: ModelRequest, handler: Callable[[ModelRequest], Awaitable[ModelResponse]]
    ) -> ModelResponse:
        state = request.state
        state_messages = state.get("messages", [])

        if _has_session_recall(state_messages) or _has_session_recall(request.messages):
            return await handler(request)

        context = getattr(request.runtime, "context", None) if request.runtime else None
        if not context:
            return await handler(request)

        from myrm_agent_harness.agent._skill_agent_context import get_memory_manager

        manager: MemoryManager | None = get_memory_manager()
        if not manager:
            return await handler(request)

        if manager.recall_mode == RecallMode.TOOLS:
            return await handler(request)

        query = _extract_query(request.messages)
        if len(query) < _MIN_QUERY_LENGTH:
            return await handler(request)

        config = getattr(manager, "_config", None)
        if config and not getattr(config, "auto_session_recall_enabled", True):
            return await handler(request)

        threshold = getattr(config, "auto_session_recall_threshold", _DEFAULT_THRESHOLD) if config else _DEFAULT_THRESHOLD
        budget_tokens = getattr(config, "auto_session_recall_budget_tokens", _DEFAULT_BUDGET_TOKENS) if config else _DEFAULT_BUDGET_TOKENS
        timeout = getattr(config, "auto_session_recall_timeout", _DEFAULT_TIMEOUT) if config else _DEFAULT_TIMEOUT

        try:
            conv_count = await asyncio.wait_for(
                manager.count_memories(MemoryType.CONVERSATION),
                timeout=1.0,
            )
            if conv_count == 0:
                return await handler(request)
        except Exception as exc:
            logger.debug("[AutoSessionRecall] count_memories failed: %s, proceeding to search", exc)

        try:
            results: list[MemorySearchResult] = await asyncio.wait_for(
                manager.search(
                    query,
                    memory_types=[MemoryType.CONVERSATION, MemoryType.TASK_DIGEST],
                    limit=5,
                    use_rrf=True,
                ),
                timeout=timeout,
            )
        except TimeoutError:
            logger.info("[AutoSessionRecall] search timed out after %.1fs, skipping", timeout)
            return await handler(request)
        except Exception as exc:
            logger.warning("[AutoSessionRecall] search failed: %s", exc)
            return await handler(request)

        filtered = [r for r in results if r.score >= threshold][:_MAX_RESULTS]
        if not filtered:
            return await handler(request)

        body = _format_recall_body(filtered, budget_tokens)
        if not body:
            return await handler(request)

        wrapped = wrap_untrusted(body, source="auto_session_recall")
        injection_content = (
            f'{_SESSION_RECALL_MARKER} count="{len(filtered)}">\n'
            f"## Relevant Prior Context (auto-recalled)\n"
            f"{wrapped}\n"
            f"Note: This context was automatically recalled from your conversation history. "
            f"Use it if relevant; ignore if not applicable to the current query.\n"
            f"</auto_session_recall>"
        )

        recall_msg = HumanMessage(content=injection_content)
        new_messages = list(request.messages)

        insert_idx = len(new_messages)
        for i, msg in enumerate(new_messages):
            if isinstance(msg, HumanMessage):
                insert_idx = i
                break
        new_messages.insert(insert_idx, recall_msg)
        state_messages.insert(insert_idx, recall_msg)

        logger.info(
            "[AutoSessionRecall] injected %d results (top score: %.3f) for query: %.60s",
            len(filtered),
            filtered[0].score,
            query,
        )

        return await handler(request.override(messages=new_messages))


auto_session_recall_middleware = AutoSessionRecallMiddleware()
