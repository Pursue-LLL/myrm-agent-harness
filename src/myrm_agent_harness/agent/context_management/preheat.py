"""Prefix cache preheat after idle compression.

Sends a lightweight LLM request (max_tokens=1) with the compressed message
context so that providers with explicit prefix caching (Anthropic, Qwen)
pre-warm the cache.  The next real user message then hits the cache instead
of a cold start.

Providers with automatic prefix caching (OpenAI, DeepSeek, Gemini) are
skipped because they handle cache warming implicitly.

[INPUT]
- langchain_core.messages::BaseMessage (POS: LangChain message base class)
- langchain_core.language_models.chat_models::BaseChatModel (POS: LangChain chat model)

[OUTPUT]
- preheat_prefix_cache: async function that sends a cache-warming probe.

[POS]
Prefix cache preheat utility for idle compression pipeline.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import BaseMessage

logger = logging.getLogger(__name__)

_EXPLICIT_CACHE_PREFIXES = ("anthropic/", "claude-", "qwen", "dashscope/", "openai/qwen")


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
    """Send a minimal probe to warm the provider's prefix cache.

    Args:
        llm: Chat model instance to invoke.
        messages: Compressed message list that forms the cacheable prefix.
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
        await llm.ainvoke(messages, max_tokens=1)
        logger.info("Prefix cache preheated for %s (%d messages)", model_name, len(messages))
        return True
    except Exception:
        logger.warning("Prefix cache preheat failed for %s", model_name, exc_info=True)
        return False
