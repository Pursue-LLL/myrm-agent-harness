"""Streamed single-model collection primitive for consensus (MoA).

[INPUT]
- langchain_core.language_models::BaseChatModel (POS: any LangChain chat model)
- langchain_core.messages::BaseMessage

[OUTPUT]
- collect_stream(): stream one model into a single answer string

[POS]
Shared streaming primitive used by both reference and aggregator calls so the
LLM adapter records per-call token usage and cost on its streaming path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import BaseMessage


async def collect_stream(
    llm: BaseChatModel,
    messages: list[BaseMessage],
    temperature: float,
    max_tokens: int | None = None,
) -> str:
    """Stream a model's answer into a single string.

    Consumes the model via streaming so the LLM adapter records per-call token
    usage and cost into the request-scoped tracker; the adapter records usage
    only on its streaming path.

    ``temperature`` is bound per call so each role (reference vs aggregator)
    uses its configured sampling value without mutating the shared, cached
    model instance; ``litellm.drop_params`` ignores it for models that do not
    accept a custom temperature.

    ``max_tokens``, when set, caps the output length.  Used by reference calls
    to limit advisor verbosity (the aggregator only needs concise advice).
    ``None`` (default) omits the parameter, preserving prior uncapped behavior.

    Falls back to ``reasoning_content`` when a reasoning model (e.g.
    DeepSeek-R1, GLM) streams its answer there with an empty ``content``.
    """
    bind_kwargs: dict[str, object] = {"temperature": temperature}
    if max_tokens is not None:
        bind_kwargs["max_tokens"] = max_tokens
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    async for chunk in llm.bind(**bind_kwargs).astream(messages):
        if chunk.content:
            content_parts.append(str(chunk.content))
            continue
        reasoning: object = chunk.additional_kwargs.get("reasoning_content")
        if reasoning:
            reasoning_parts.append(str(reasoning))
    return "".join(content_parts) or "".join(reasoning_parts)
