"""Passive LLM request observability for EventLog replay.

Appends truncated prompt previews to the event log without mutating LLM
messages or affecting prompt prefix cache behavior.

[INPUT]
- agent.middlewares._session_context::get_event_logger (POS: Per-request EventLogger ContextVar)

[OUTPUT]
- build_prompt_preview: truncate assembled messages for replay display
- record_llm_request: append llm_request event to the session event log

[POS]
Harness observability helper. Called from the LLM adapter immediately before
API invocation — read-only with respect to the messages sent to the model.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

PROMPT_PREVIEW_MAX_LEN = 500

_pending_tasks: set[asyncio.Task[None]] = set()


def build_prompt_preview(
    message_dicts: list[dict[str, object]], *, max_len: int = PROMPT_PREVIEW_MAX_LEN
) -> str:
    """Build a truncated preview of messages for replay — never mutates inputs."""
    parts: list[str] = []
    for msg in message_dicts:
        role = msg.get("role", "?")
        content = msg.get("content", "")
        if isinstance(content, str) and content.strip():
            parts.append(f"[{role}] {content.strip()}")
        elif msg.get("tool_calls"):
            parts.append(f"[{role}] <tool_calls>")
    if not parts:
        return ""
    combined = "\n".join(parts)
    if len(combined) <= max_len:
        return combined
    omitted = len(combined) - max_len
    return f"{combined[:max_len]}... ({omitted} chars truncated)"


async def record_llm_request(model_name: str, message_dicts: list[dict[str, object]]) -> None:
    """Record an llm_request event if an EventLogger is active in the current context."""
    from myrm_agent_harness.agent.middlewares._session_context import get_event_logger

    event_logger = get_event_logger()
    if event_logger is None:
        return
    try:
        await event_logger.log(
            "llm_request",
            {
                "model_name": model_name,
                "prompt_preview": build_prompt_preview(message_dicts),
                "message_count": len(message_dicts),
            },
        )
    except Exception:
        logger.debug("Failed to record llm_request event", exc_info=True)


_observability_hook_installed = False


def install_llm_observability_hook() -> None:
    """Register ``record_llm_request`` as an LLM request hook (idempotent).

    Uses ``asyncio.ensure_future`` to bridge sync hook → async recording.
    """
    global _observability_hook_installed
    if _observability_hook_installed:
        return
    _observability_hook_installed = True

    from myrm_agent_harness.toolkits.llms.utils.logger import register_request_hook

    def _sync_record_llm_request(model_name: str, message_dicts: list[dict[str, object]]) -> None:
        try:
            loop = asyncio.get_running_loop()
            task = loop.create_task(record_llm_request(model_name, message_dicts))
            _pending_tasks.add(task)
            task.add_done_callback(_pending_tasks.discard)
        except RuntimeError:
            pass

    register_request_hook(_sync_record_llm_request)
