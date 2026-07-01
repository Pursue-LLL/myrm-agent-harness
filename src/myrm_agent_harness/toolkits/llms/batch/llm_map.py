"""Lightweight batch LLM-map primitive.

Applies one shared instruction to N items concurrently, with per-item failure
isolation, cancellation, progress reporting and optional structured output.
Unlike sub-agent delegation this spawns no agent loops — each item is a single
bounded LLM call — making it the cheap, deterministic primitive for bulk
per-item work (summarise / classify / translate / extract over many inputs).

Prompt-cache positive by construction: the shared instruction is emitted as a
stable ``SystemMessage`` prefix while only the per-item payload varies in the
``HumanMessage`` suffix, so the provider KV-cache is hit across the fan-out.

[INPUT]
- langchain_core.language_models::BaseChatModel (POS: LangChain chat model interface)
- langchain_core.messages::HumanMessage, SystemMessage (POS: prompt message types)
- infra.concurrency.limiter::ConcurrencyLimiter (POS: bounded async concurrency)
- toolkits.llms.errors.resilient::resilient_llm_call (POS: per-call failover primitive)
- utils.runtime.cancellation::CancellationToken (POS: cooperative cancellation)

[OUTPUT]
- LlmMapItemResult: per-item outcome (index/id/status/output/error)
- LlmMapReport: aggregate report (counts + items)
- llm_map(): execute the bounded concurrent map

[POS]
Lightweight batch LLM-map primitive. The deterministic fan-out engine behind
the ``llm_map`` agent tool and PTC scripts.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from myrm_agent_harness.infra.concurrency.limiter import ConcurrencyLimiter
from myrm_agent_harness.toolkits.llms.errors.resilient import resilient_llm_call
from myrm_agent_harness.utils.runtime.cancellation import CancellationToken

logger = logging.getLogger(__name__)

ItemStatus = Literal["ok", "failed", "cancelled"]

# Hard ceilings — guard against runaway fan-out independent of sub-agent caps.
MAX_ITEMS_HARD_CAP = 500
MAX_CONCURRENCY_HARD_CAP = 32
DEFAULT_MAX_CONCURRENCY = 8
DEFAULT_ITEM_TIMEOUT_S = 90.0

ProgressCallback = Callable[["LlmMapProgress"], Awaitable[None]]
ItemResolver = Callable[[str], str]


@dataclass(slots=True, frozen=True)
class LlmMapProgress:
    """Snapshot pushed to the progress callback after each item settles."""

    done: int
    total: int
    failed: int


@dataclass(slots=True)
class LlmMapItemResult:
    """Outcome of a single mapped item.

    ``output`` is text for free-form mapping or a JSON-serialisable dict when a
    ``response_schema`` is supplied. ``error`` is populated only on failure.
    """

    index: int
    id: str
    status: ItemStatus
    output: str | dict[str, object] | None = None
    error: str | None = None


@dataclass(slots=True)
class LlmMapReport:
    """Aggregate result of an :func:`llm_map` run."""

    total: int
    succeeded: int
    failed: int
    cancelled: int
    items: list[LlmMapItemResult] = field(default_factory=list)


def _normalise_item(index: int, item: str | dict[str, object], resolver: ItemResolver | None) -> tuple[str, str]:
    """Return ``(stable_id, content)`` for an input item.

    Dict items may carry an explicit ``id`` so callers can re-join results to
    their source rows; ``vault://`` payloads are resolved lazily via *resolver*
    to keep large inputs out of the model context until needed.
    """
    if isinstance(item, dict):
        raw_id = item.get("id")
        item_id = str(raw_id) if raw_id is not None else str(index)
        content = item.get("content", item.get("text", ""))
        content = content if isinstance(content, str) else str(content)
    else:
        item_id = str(index)
        content = item

    if resolver is not None and content.startswith("vault://"):
        content = resolver(content)
    return item_id, content


def _extract_text(response: object) -> str:
    """Coerce an LLM response into plain text across provider content shapes."""
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [seg.get("text", "") if isinstance(seg, dict) else str(seg) for seg in content]
        return "".join(parts)
    return str(content)


async def llm_map(
    llm: BaseChatModel,
    items: Sequence[str | dict[str, object]],
    instruction: str,
    *,
    fallback_llm: BaseChatModel | None = None,
    response_schema: type[BaseModel] | None = None,
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    item_timeout: float = DEFAULT_ITEM_TIMEOUT_S,
    cancel_token: CancellationToken | None = None,
    on_progress: ProgressCallback | None = None,
    item_resolver: ItemResolver | None = None,
    warm_prefix: bool = True,
) -> LlmMapReport:
    """Apply *instruction* to every item in *items* with bounded concurrency.

    Each item becomes one ``[System(instruction), Human(content)]`` call. Per
    item failures are isolated into :class:`LlmMapItemResult` (status=``failed``)
    so a single bad row never aborts the batch. Cancellation is honoured between
    and during items via *cancel_token*; in-flight items are also capped by
    *item_timeout*.

    When *warm_prefix* is set **and** the batch is large enough (>=4 items with
    concurrency >=2), the first item runs alone before the remainder fan out.
    This gives the provider an opportunity to cache the shared System-message
    prefix so concurrent calls may benefit from a cache hit.  For small batches
    the overhead of an extra serial round-trip outweighs any cache benefit, so
    the warm-up is skipped automatically.
    """
    instruction = instruction.strip()
    if not instruction:
        raise ValueError("llm_map requires a non-empty instruction")
    if not items:
        return LlmMapReport(total=0, succeeded=0, failed=0, cancelled=0)

    concurrency = max(1, min(max_concurrency, MAX_CONCURRENCY_HARD_CAP))
    limiter = ConcurrencyLimiter(concurrency)
    structured_llm = llm.with_structured_output(response_schema) if response_schema else None
    structured_fallback = (
        fallback_llm.with_structured_output(response_schema) if (response_schema and fallback_llm is not None) else None
    )

    total = len(items)
    counters = {"done": 0, "failed": 0}

    async def _invoke(content: str) -> str | dict[str, object]:
        messages = [SystemMessage(content=instruction), HumanMessage(content=content)]
        if structured_llm is not None:
            obj = await resilient_llm_call(
                primary_fn=lambda: structured_llm.ainvoke(messages),
                fallback_fn=(lambda: structured_fallback.ainvoke(messages)) if structured_fallback else None,
            )
            return obj.model_dump() if isinstance(obj, BaseModel) else {"value": obj}
        response = await resilient_llm_call(
            primary_fn=lambda: llm.ainvoke(messages),
            fallback_fn=(lambda: fallback_llm.ainvoke(messages)) if fallback_llm else None,
        )
        return _extract_text(response)

    async def _process(index: int, item: str | dict[str, object]) -> LlmMapItemResult:
        try:
            item_id, content = _normalise_item(index, item, item_resolver)
        except Exception as exc:
            raw_id = item.get("id") if isinstance(item, dict) else None
            item_id = str(raw_id) if raw_id is not None else str(index)
            logger.warning("llm_map item %s normalize failed: %s", item_id, exc)
            result = LlmMapItemResult(index=index, id=item_id, status="failed", error=str(exc))
            counters["done"] += 1
            counters["failed"] += 1
            if on_progress is not None:
                await on_progress(LlmMapProgress(done=counters["done"], total=total, failed=counters["failed"]))
            return result

        if cancel_token is not None and cancel_token.is_cancelled:
            return LlmMapItemResult(index=index, id=item_id, status="cancelled", error="run cancelled")
        try:
            async with limiter:
                if cancel_token is not None and cancel_token.is_cancelled:
                    return LlmMapItemResult(index=index, id=item_id, status="cancelled", error="run cancelled")
                output = await asyncio.wait_for(_invoke(content), timeout=item_timeout)
            result = LlmMapItemResult(index=index, id=item_id, status="ok", output=output)
        except TimeoutError:
            result = LlmMapItemResult(index=index, id=item_id, status="failed", error=f"timeout after {item_timeout}s")
        except asyncio.CancelledError:
            return LlmMapItemResult(index=index, id=item_id, status="cancelled", error="run cancelled")
        except Exception as exc:
            logger.warning("llm_map item %s failed: %s", item_id, exc)
            result = LlmMapItemResult(index=index, id=item_id, status="failed", error=str(exc))

        counters["done"] += 1
        if result.status == "failed":
            counters["failed"] += 1
        if on_progress is not None:
            await on_progress(LlmMapProgress(done=counters["done"], total=total, failed=counters["failed"]))
        return result

    results: list[LlmMapItemResult] = []
    start = 0
    if warm_prefix and total >= 4 and concurrency > 1:
        results.append(await _process(0, items[0]))
        start = 1
    if start < total:
        results.extend(await asyncio.gather(*(_process(i, items[i]) for i in range(start, total))))

    results.sort(key=lambda r: r.index)
    succeeded = sum(1 for r in results if r.status == "ok")
    failed = sum(1 for r in results if r.status == "failed")
    cancelled = sum(1 for r in results if r.status == "cancelled")
    return LlmMapReport(total=total, succeeded=succeeded, failed=failed, cancelled=cancelled, items=results)


__all__ = [
    "DEFAULT_ITEM_TIMEOUT_S",
    "DEFAULT_MAX_CONCURRENCY",
    "MAX_CONCURRENCY_HARD_CAP",
    "MAX_ITEMS_HARD_CAP",
    "ItemResolver",
    "LlmMapItemResult",
    "LlmMapProgress",
    "LlmMapReport",
    "ProgressCallback",
    "llm_map",
]
