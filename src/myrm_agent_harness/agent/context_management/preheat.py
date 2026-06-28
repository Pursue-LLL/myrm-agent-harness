"""Prefix cache preheat for explicit-cache providers.

Forces providers with explicit prefix caching (Anthropic, Qwen) to write
the prompt prefix into their server-side cache before the first real user
request arrives, eliminating the cold-start latency tax on TTFT.

Two usage patterns:
1. **Agent init preheat** — called from ``BaseAgent._ensure_initialized()``
   right after the system prompt is built.  The user is still typing, so
   the cache is warm by the time the first message is sent.
2. **Post-compaction preheat** — ``preheat_prefix_cache`` is exposed as a
   public API for callers that rewrite the message list (e.g. context
   compaction pipelines) and need to re-warm the prefix cache afterward.

Anthropic official best practice: send ``max_tokens=0`` (zero output) with
``cache_control`` on the system block.  The API writes the cache without
generating any output tokens.

Providers with automatic prefix caching (OpenAI, DeepSeek, Gemini) are
skipped because they handle cache warming implicitly.

Ref: https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching

[INPUT]
- langchain_core.messages::BaseMessage (POS: LangChain message base class)
- langchain_core.language_models.chat_models::BaseChatModel (POS: LangChain chat model)

[OUTPUT]
- preheat_prefix_cache: async function that sends a cache-warming probe.
- schedule_init_preheat: fire-and-forget init-time preheat for system prompt prefix.

[POS]
Prefix cache preheat utility for agent init and post-compaction pipelines.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import BaseMessage

logger = logging.getLogger(__name__)

_EXPLICIT_CACHE_PREFIXES = ("anthropic/", "claude-", "qwen", "dashscope/", "openai/qwen")

# Anthropic minimum cacheable prefix length (Sonnet 4 family)
_MIN_PREHEAT_TOKENS = 1024


def needs_explicit_preheat(model_name: str) -> bool:
    """Return True for providers that require explicit cache-control markers."""
    if not model_name:
        return False
    model_lower = model_name.lower()
    return any(model_lower.startswith(p) for p in _EXPLICIT_CACHE_PREFIXES)


async def preheat_prefix_cache(
    llm: BaseChatModel,
    messages: Sequence[BaseMessage],
    model_name: str,
) -> bool:
    """Send a zero-output probe to warm the provider's prefix cache.

    Uses ``max_tokens=0`` per Anthropic official best practice to avoid
    generating any output tokens.  Falls back to ``max_tokens=1`` if the
    provider rejects zero (older LiteLLM versions or non-Anthropic explicit
    cache providers).

    Args:
        llm: Chat model instance to invoke.
        messages: Message list that forms the cacheable prefix.
        model_name: Model identifier for provider detection.

    Returns:
        True if the preheat succeeded, False otherwise.
    """
    if not needs_explicit_preheat(model_name):
        logger.debug("Skipping preheat for auto-cache provider: %s", model_name)
        return False

    if not messages:
        return False

    try:
        await llm.ainvoke(messages, max_tokens=0)
        logger.info("Prefix cache preheated for %s (%d messages)", model_name, len(messages))
        return True
    except (ValueError, TypeError):
        try:
            await llm.ainvoke(messages, max_tokens=1)
            logger.info("Prefix cache preheated (fallback max_tokens=1) for %s", model_name)
            return True
        except Exception:
            logger.warning("Prefix cache preheat failed for %s", model_name, exc_info=True)
            return False
    except Exception:
        logger.warning("Prefix cache preheat failed for %s", model_name, exc_info=True)
        return False


def schedule_init_preheat(
    llm: BaseChatModel,
    system_prompt: str | None,
    model_name: str,
) -> None:
    """Fire-and-forget preheat of the system prompt prefix at agent init.

    Called at the end of ``BaseAgent._ensure_initialized()`` to pre-warm the
    Anthropic server-side cache while the user is still typing.  The preheat
    runs as a background ``asyncio.Task`` and never blocks initialization.

    Skipped when:
    - model is not an explicit-cache provider
    - system_prompt is None/empty (FORK context mode)
    - estimated tokens < _MIN_PREHEAT_TOKENS (below Anthropic minimum)
    """
    if not system_prompt or not needs_explicit_preheat(model_name):
        return

    from myrm_agent_harness.utils.token_estimation import estimate_content_tokens

    token_count = estimate_content_tokens(system_prompt)
    if token_count < _MIN_PREHEAT_TOKENS:
        logger.debug(
            "Skipping init preheat: system prompt too short (%d tokens < %d minimum)",
            token_count,
            _MIN_PREHEAT_TOKENS,
        )
        return

    async def _do_preheat() -> None:
        from langchain_core.messages import HumanMessage, SystemMessage

        msgs: list[BaseMessage] = [SystemMessage(content=system_prompt), HumanMessage(content="warmup")]
        result = await preheat_prefix_cache(llm, msgs, model_name)
        if result:
            logger.info(
                "Init preheat completed: %s (%d system prompt tokens cached)",
                model_name,
                token_count,
            )

    try:
        asyncio.get_running_loop().create_task(_do_preheat())
    except RuntimeError:
        logger.debug("No running event loop for init preheat; skipping")
