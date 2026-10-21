"""Reference fan-out for the consensus engine.

[INPUT]
- langchain_core.language_models::BaseChatModel
- langchain_core.messages::BaseMessage
- .types::ConsensusConfig, ReferenceResponse
- utils.runtime.cancellation::CancellationToken

[OUTPUT]
- model_name_of: model name extraction shared with the engine
- query_single / query_references: per-model retry and parallel fan-out

[POS]
Framework-level parallel reference querying for MoA, split out of the engine
so consensus/engine.py stays within the line-count gate. Mirrors the module
split already used by _streaming and _prompts.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from myrm_agent_harness.toolkits.llms.consensus._streaming import collect_stream
from myrm_agent_harness.toolkits.llms.consensus.types import (
    ConsensusConfig,
    ReferenceResponse,
)
from myrm_agent_harness.utils.runtime.cancellation import CancellationToken

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


def model_name_of(llm: BaseChatModel) -> str:
    """Extract a human-readable model name."""
    for attr in ("model_name", "model", "name"):
        val = getattr(llm, attr, None)
        if val and isinstance(val, str):
            return val
    return type(llm).__name__


async def query_single(
    llm: BaseChatModel,
    query: str,
    system_prompt: str | None,
    chat_history: list[BaseMessage] | None,
    cfg: ConsensusConfig,
) -> ReferenceResponse:
    """Query one reference model with retry and per-model timeout."""
    model = model_name_of(llm)

    messages: list[BaseMessage] = []
    if system_prompt:
        messages.append(SystemMessage(content=system_prompt))
    if chat_history:
        messages.extend(chat_history)
    messages.append(HumanMessage(content=query))

    last_error = ""
    t0 = time.monotonic()
    for attempt in range(1, cfg.max_retries_per_model + 1):
        t0 = time.monotonic()
        try:
            streamed = await asyncio.wait_for(
                collect_stream(
                    llm,
                    messages,
                    cfg.reference_temperature,
                    cfg.reference_max_tokens,
                    cfg.reference_reasoning_effort,
                ),
                timeout=cfg.timeout_per_model,
            )
            content = streamed.strip()
            if not content:
                last_error = "empty response"
                logger.warning("%s returned empty (attempt %d)", model, attempt)
                if attempt < cfg.max_retries_per_model:
                    await asyncio.sleep(min(2**attempt, 30))
                    continue
                break

            elapsed = time.monotonic() - t0
            logger.info("%s responded (%d chars, %.1fs)", model, len(content), elapsed)
            return ReferenceResponse(
                model=model,
                content=content,
                elapsed_seconds=elapsed,
                success=True,
            )

        except TimeoutError:
            last_error = f"timeout ({cfg.timeout_per_model}s)"
            logger.warning("%s timed out (attempt %d)", model, attempt)
        except Exception as exc:
            last_error = str(exc)
            logger.warning("%s error (attempt %d): %s", model, attempt, last_error)

        if attempt < cfg.max_retries_per_model:
            await asyncio.sleep(min(2**attempt, 30))

    elapsed = time.monotonic() - t0
    return ReferenceResponse(
        model=model,
        content="",
        elapsed_seconds=elapsed,
        success=False,
        error=last_error,
    )


async def query_references(
    refs: list[BaseChatModel],
    query: str,
    system_prompt: str | None,
    chat_history: list[BaseMessage] | None,
    cfg: ConsensusConfig,
    cancel_token: CancellationToken | None = None,
) -> list[ReferenceResponse]:
    """Fan-out to all reference models in parallel (batch mode)."""
    if cancel_token and cancel_token.is_cancelled:
        return []

    tasks = [query_single(llm, query, system_prompt, chat_history, cfg) for llm in refs]
    try:
        return list(
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=False),
                timeout=cfg.timeout_total,
            )
        )
    except TimeoutError:
        logger.warning("Consensus global timeout (%.0fs)", cfg.timeout_total)
        return [
            ReferenceResponse(
                model=model_name_of(llm),
                content="",
                elapsed_seconds=cfg.timeout_total,
                success=False,
                error="global timeout",
            )
            for llm in refs
        ]
