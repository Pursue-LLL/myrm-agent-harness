"""Consensus (MoA) inference engine.

Parallel-queries multiple reference LLMs, then synthesises via an
aggregator LLM.  Designed around ``BaseChatModel`` so that any
LangChain-compatible model (ChatLiteLLM, KeyPoolLLM, ManagedLLM …)
works out of the box.

[INPUT]
- langchain_core.language_models::BaseChatModel
- ._prompts::build_aggregation_messages (POS: persona-aware aggregator prompt builder)
- ._streaming::collect_stream (POS: shared stream-to-string collector with reasoning fallback)
- .types::ConsensusConfig, ConsensusResult, ReferenceResponse
- utils.runtime.cancellation::CancellationToken (POS: async cancellation token)

[OUTPUT]
- ConsensusEngine: stateless engine; ``run()`` for batch, ``run_stream()`` for streaming
- ConsensusStreamEvent: event type for streaming consensus runs

[POS]
Framework-level multi-model consensus inference engine.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from langchain_core.messages import HumanMessage, SystemMessage

from myrm_agent_harness.toolkits.llms.consensus._prompts import (
    build_aggregation_messages,
)
from myrm_agent_harness.toolkits.llms.consensus._streaming import collect_stream
from myrm_agent_harness.toolkits.llms.consensus.types import (
    ConsensusConfig,
    ConsensusResult,
    ReferenceResponse,
)
from myrm_agent_harness.utils.runtime.cancellation import CancellationToken

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ConsensusStreamEvent:
    """Event emitted during a streaming consensus run.

    ``kind`` values:
    - ``"ref_done"``: a reference model finished; ``ref`` is set.
    - ``"agg_chunk"``: a token chunk from the aggregator; ``chunk`` is set.
    - ``"done"``: final result; ``result`` is set.
    """

    kind: Literal["ref_done", "agg_chunk", "done"]
    ref: ReferenceResponse | None = None
    chunk: str | None = None
    result: ConsensusResult | None = None


class ConsensusEngine:
    """Stateless multi-model consensus (MoA) engine.

    Usage::

        engine = ConsensusEngine(
            reference_llms=[llm_a, llm_b, llm_c],
            aggregator_llm=llm_agg,
        )
        result = await engine.run("Prove sqrt(2) is irrational")
    """

    def __init__(
        self,
        reference_llms: list[BaseChatModel],
        aggregator_llm: BaseChatModel,
        config: ConsensusConfig | None = None,
    ) -> None:
        if not reference_llms:
            raise ValueError("At least one reference LLM is required")
        self._refs = reference_llms
        self._agg = aggregator_llm
        self._cfg = config or ConsensusConfig()

    async def run(
        self,
        query: str,
        *,
        system_prompt: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> ConsensusResult:
        """Execute a full consensus run.

        Args:
            query: the user question / task.
            system_prompt: optional agent persona/instructions.  Applied to
                each reference call and prepended to the aggregator's synthesis
                prompt so the final answer honours the same persona, language
                and format.
            cancel_token: optional cancellation token; checked before
                each phase to abort early and avoid wasted API calls.

        Returns:
            ``ConsensusResult`` with the final answer, per-model
            responses, and timing data.
        """
        t0 = time.monotonic()
        cfg = self._cfg

        if cancel_token and cancel_token.is_cancelled:
            return self._cancelled_result(t0)

        ref_responses = await self._query_references(query, system_prompt, cancel_token)

        if cancel_token and cancel_token.is_cancelled:
            return self._cancelled_result(t0, ref_responses)

        successful = [r for r in ref_responses if r.success]
        if len(successful) < cfg.min_successful:
            elapsed = time.monotonic() - t0
            return ConsensusResult(
                final_answer="",
                reference_responses=ref_responses,
                aggregator_model=self._model_name(self._agg),
                elapsed_seconds=elapsed,
                success=False,
                error=(
                    f"Only {len(successful)}/{len(ref_responses)} reference models succeeded (min={cfg.min_successful})"
                ),
            )

        if len(successful) == 1:
            logger.info(
                "Consensus: 1 reference succeeded, returning it without aggregation (%s)",
                successful[0].model,
            )
            return self._success_result(successful[0].content, ref_responses, t0)

        final = await self._aggregate(query, successful, system_prompt)

        logger.info(
            "Consensus complete: %d/%d refs OK, %.1fs total",
            len(successful),
            len(ref_responses),
            time.monotonic() - t0,
        )
        return self._success_result(final, ref_responses, t0)

    async def run_stream(
        self,
        query: str,
        *,
        system_prompt: str | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> AsyncIterator[ConsensusStreamEvent]:
        """Execute a consensus run with streaming aggregation output.

        Yields ``ConsensusStreamEvent`` objects:
        1. One ``ref_done`` per reference model as it completes.
        2. Multiple ``agg_chunk`` events as the aggregator streams tokens.
        3. One ``done`` event with the final ``ConsensusResult``.
        """
        t0 = time.monotonic()
        cfg = self._cfg

        if cancel_token and cancel_token.is_cancelled:
            yield ConsensusStreamEvent(kind="done", result=self._cancelled_result(t0))
            return

        # Progressive yield: emit ref_done as each model completes (not all-at-once).
        ref_responses: list[ReferenceResponse] = []
        if not (cancel_token and cancel_token.is_cancelled):
            tasks = [
                asyncio.ensure_future(self._query_single(llm, query, system_prompt))
                for llm in self._refs
            ]
            try:
                for coro in asyncio.as_completed(tasks, timeout=cfg.timeout_total):
                    ref = await coro
                    ref_responses.append(ref)
                    yield ConsensusStreamEvent(kind="ref_done", ref=ref)
                    if cancel_token and cancel_token.is_cancelled:
                        break
            except TimeoutError:
                logger.warning("Consensus global timeout (%.0fs)", cfg.timeout_total)
                for task in tasks:
                    if not task.done():
                        task.cancel()
                        ref_responses.append(
                            ReferenceResponse(
                                model="unknown",
                                content="",
                                elapsed_seconds=cfg.timeout_total,
                                success=False,
                                error="global timeout",
                            )
                        )

        if cancel_token and cancel_token.is_cancelled:
            yield ConsensusStreamEvent(kind="done", result=self._cancelled_result(t0, ref_responses))
            return

        successful = [r for r in ref_responses if r.success]
        if len(successful) < cfg.min_successful:
            yield ConsensusStreamEvent(
                kind="done",
                result=ConsensusResult(
                    final_answer="",
                    reference_responses=ref_responses,
                    aggregator_model=self._model_name(self._agg),
                    elapsed_seconds=time.monotonic() - t0,
                    success=False,
                    error=(
                        f"Only {len(successful)}/{len(ref_responses)} reference "
                        f"models succeeded (min={cfg.min_successful})"
                    ),
                ),
            )
            return

        if len(successful) == 1:
            single = successful[0]
            logger.info(
                "Consensus stream: 1 reference succeeded, returning it without aggregation (%s)",
                single.model,
            )
            yield ConsensusStreamEvent(kind="agg_chunk", chunk=single.content)
            yield ConsensusStreamEvent(
                kind="done",
                result=self._success_result(single.content, ref_responses, t0),
            )
            return

        final_chunks: list[str] = []
        async for chunk in self._aggregate_stream(query, successful, cancel_token, system_prompt):
            final_chunks.append(chunk)
            yield ConsensusStreamEvent(kind="agg_chunk", chunk=chunk)

        final_answer = "".join(final_chunks)
        if not final_answer:
            best = max(successful, key=lambda r: len(r.content))
            final_answer = best.content

        logger.info(
            "Consensus stream complete: %d/%d refs OK, %.1fs total",
            len(successful),
            len(ref_responses),
            time.monotonic() - t0,
        )
        yield ConsensusStreamEvent(
            kind="done",
            result=self._success_result(final_answer, ref_responses, t0),
        )

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _cancelled_result(
        self,
        t0: float,
        ref_responses: list[ReferenceResponse] | None = None,
    ) -> ConsensusResult:
        """Build a result for a cancelled run."""
        return ConsensusResult(
            final_answer="",
            reference_responses=ref_responses or [],
            aggregator_model=self._model_name(self._agg),
            elapsed_seconds=time.monotonic() - t0,
            success=False,
            error="cancelled",
        )

    def _success_result(
        self,
        final_answer: str,
        ref_responses: list[ReferenceResponse],
        t0: float,
    ) -> ConsensusResult:
        """Build a successful result, stamping elapsed time from ``t0``."""
        return ConsensusResult(
            final_answer=final_answer,
            reference_responses=ref_responses,
            aggregator_model=self._model_name(self._agg),
            elapsed_seconds=time.monotonic() - t0,
        )

    async def _query_references(
        self,
        query: str,
        system_prompt: str | None,
        cancel_token: CancellationToken | None = None,
    ) -> list[ReferenceResponse]:
        """Fan-out to all reference models in parallel."""
        if cancel_token and cancel_token.is_cancelled:
            return []

        tasks = [self._query_single(llm, query, system_prompt) for llm in self._refs]
        try:
            return list(
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=False),
                    timeout=self._cfg.timeout_total,
                )
            )
        except TimeoutError:
            logger.warning("Consensus global timeout (%.0fs)", self._cfg.timeout_total)
            return [
                ReferenceResponse(
                    model=self._model_name(llm),
                    content="",
                    elapsed_seconds=self._cfg.timeout_total,
                    success=False,
                    error="global timeout",
                )
                for llm in self._refs
            ]

    async def _query_single(
        self,
        llm: BaseChatModel,
        query: str,
        system_prompt: str | None,
    ) -> ReferenceResponse:
        """Query one reference model with retry and per-model timeout."""
        model_name = self._model_name(llm)
        cfg = self._cfg

        messages: list[SystemMessage | HumanMessage] = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        messages.append(HumanMessage(content=query))

        last_error = ""
        t0 = time.monotonic()
        for attempt in range(1, cfg.max_retries_per_model + 1):
            t0 = time.monotonic()
            try:
                streamed = await asyncio.wait_for(
                    collect_stream(llm, messages, cfg.reference_temperature),
                    timeout=cfg.timeout_per_model,
                )
                content = streamed.strip()
                if not content:
                    last_error = "empty response"
                    logger.warning("%s returned empty (attempt %d)", model_name, attempt)
                    if attempt < cfg.max_retries_per_model:
                        await asyncio.sleep(min(2**attempt, 30))
                        continue
                    break

                elapsed = time.monotonic() - t0
                logger.info("%s responded (%d chars, %.1fs)", model_name, len(content), elapsed)
                return ReferenceResponse(
                    model=model_name,
                    content=content,
                    elapsed_seconds=elapsed,
                    success=True,
                )

            except TimeoutError:
                last_error = f"timeout ({cfg.timeout_per_model}s)"
                logger.warning("%s timed out (attempt %d)", model_name, attempt)
            except Exception as exc:
                last_error = str(exc)
                logger.warning("%s error (attempt %d): %s", model_name, attempt, last_error)

            if attempt < cfg.max_retries_per_model:
                await asyncio.sleep(min(2**attempt, 30))

        elapsed = time.monotonic() - t0
        return ReferenceResponse(
            model=model_name,
            content="",
            elapsed_seconds=elapsed,
            success=False,
            error=last_error,
        )

    async def _aggregate(
        self,
        query: str,
        successful: list[ReferenceResponse],
        system_prompt: str | None = None,
    ) -> str:
        """Synthesise successful reference responses (batch mode).

        Consumes the aggregator via ``astream`` so its token usage is recorded
        by the LLM adapter, keeping batch cost accounting on par with reference
        calls and the streaming aggregation path.

        ``system_prompt`` is threaded into the aggregator prompt so the synthesis
        honours the same agent persona as the references (see
        ``build_aggregation_messages``).
        """
        messages = build_aggregation_messages(query, successful, system_prompt)
        try:
            for attempt in (1, 2):
                streamed = await asyncio.wait_for(
                    collect_stream(self._agg, messages, self._cfg.aggregator_temperature),
                    timeout=self._cfg.timeout_per_model,
                )
                content = streamed.strip()
                if content:
                    return content
                if attempt == 1:
                    logger.warning("Aggregator returned empty, retrying once")
            return ""
        except Exception as exc:
            logger.error("Aggregator failed: %s", exc)
            best = max(successful, key=lambda r: len(r.content))
            logger.info("Falling back to best reference response (%s)", best.model)
            return best.content

    async def _aggregate_stream(
        self,
        query: str,
        successful: list[ReferenceResponse],
        cancel_token: CancellationToken | None = None,
        system_prompt: str | None = None,
    ) -> AsyncIterator[str]:
        """Stream aggregation tokens from the aggregator LLM.

        Temperature is bound per call so the aggregator uses its configured
        (focused) sampling value without mutating the shared model instance.

        ``system_prompt`` is threaded into the aggregator prompt so the streamed
        synthesis honours the same agent persona as the references (see
        ``build_aggregation_messages``).

        Mirrors ``collect_stream``'s reasoning fallback: when a reasoning model
        (e.g. DeepSeek-R1, GLM) streams its synthesis into ``reasoning_content``
        with an empty ``content``, the buffered reasoning is flushed once at the
        end so the synthesis is preserved. Content models stream token-by-token
        unchanged.

        On a mid-stream failure the best reference is yielded only when nothing
        has been emitted yet; once partial synthesis has streamed, splicing a
        full raw reference onto it would corrupt the answer, so the partial
        output is kept as-is.
        """
        messages = build_aggregation_messages(query, successful, system_prompt)
        agg = self._agg.bind(temperature=self._cfg.aggregator_temperature)
        saw_content = False
        try:
            reasoning_parts: list[str] = []
            async for chunk in agg.astream(messages):
                if cancel_token and cancel_token.is_cancelled:
                    return
                if chunk.content:
                    saw_content = True
                    yield str(chunk.content)
                    continue
                reasoning: object = chunk.additional_kwargs.get("reasoning_content")
                if reasoning:
                    reasoning_parts.append(str(reasoning))
            if not saw_content and reasoning_parts:
                yield "".join(reasoning_parts)
        except Exception as exc:
            logger.error("Aggregator stream failed: %s", exc)
            if saw_content:
                return
            best = max(successful, key=lambda r: len(r.content))
            logger.info("Falling back to best reference response (%s)", best.model)
            yield best.content

    @staticmethod
    def _model_name(llm: BaseChatModel) -> str:
        """Extract a human-readable model name."""
        for attr in ("model_name", "model", "name"):
            val = getattr(llm, attr, None)
            if val and isinstance(val, str):
                return val
        return type(llm).__name__
