"""Parallel advisor fan-out for agent-loop MoA overlay."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from myrm_agent_harness.toolkits.llms.consensus._history import flatten_tool_free_history
from myrm_agent_harness.toolkits.llms.consensus._streaming import collect_stream
from myrm_agent_harness.toolkits.llms.consensus.advisor_prompts import ADVISOR_SYSTEM
from myrm_agent_harness.toolkits.llms.consensus.moa_overlay_types import MoAOverlayConfig
from myrm_agent_harness.toolkits.llms.consensus.types import PrivacyFilterMode, ReferenceResponse

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


def _redact_for_privacy(text: str, mode: PrivacyFilterMode) -> str:
    if mode == "off" or not text:
        return text
    from myrm_agent_harness.agent.security.redact import redact_sensitive_text

    redacted = redact_sensitive_text(text)
    if mode in ("display", "full"):
        from myrm_agent_harness.agent.security.detection.pii_redactor import redact_pii

        redacted, _ = redact_pii(redacted)
    return redacted


def _extract_last_human_query(messages: list[BaseMessage]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            content = msg.content
            if isinstance(content, str) and content.strip():
                return content.strip()
            if isinstance(content, list):
                parts = [
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                ]
                joined = " ".join(p for p in parts if p).strip()
                if joined:
                    return joined
    return ""


def _state_cache_key(messages: list[BaseMessage]) -> str:
    digest = hashlib.sha256()
    for msg in messages:
        role = type(msg).__name__
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        digest.update(f"{role}:{content[:2000]}".encode())
    return digest.hexdigest()


def should_run_fanout(
    *,
    messages: list[BaseMessage],
    fanout: str,
    every_n: int,
    iteration: int,
) -> bool:
    if fanout == "per_iteration":
        return True
    if fanout == "every_n":
        n = max(1, every_n)
        return iteration % n == 0
    # user_turn: only when the acting model call starts on a fresh user message
    if not messages:
        return False
    return isinstance(messages[-1], HumanMessage)


class AdvisorFanoutRunner:
    """Runs lightweight reference-model fan-out with per-state response cache."""

    def __init__(
        self,
        reference_llms: list[BaseChatModel],
        config: MoAOverlayConfig | None = None,
    ) -> None:
        if not reference_llms:
            raise ValueError("At least one reference LLM is required for MoA overlay")
        self._refs = reference_llms
        self._cfg = config or MoAOverlayConfig()
        self._cache: dict[str, list[ReferenceResponse]] = {}
        self._iteration = 0

    @property
    def iteration(self) -> int:
        return self._iteration

    def next_iteration(self) -> int:
        self._iteration += 1
        return self._iteration

    async def run(
        self,
        messages: list[BaseMessage],
        *,
        on_ref_done: Callable[[ReferenceResponse], Awaitable[None]] | None = None,
    ) -> list[ReferenceResponse]:
        self._iteration = self.next_iteration()
        if not should_run_fanout(
            messages=messages,
            fanout=self._cfg.fanout,
            every_n=self._cfg.every_n,
            iteration=self._iteration,
        ):
            return []

        query = _extract_last_human_query(messages)
        if not query:
            return []

        cache_key = _state_cache_key(messages)
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug("MoA overlay: cache hit for state %s", cache_key[:12])
            if on_ref_done is not None:
                for ref in cached:
                    await on_ref_done(ref)
            return cached

        flat_history = flatten_tool_free_history(messages[:-1]) if len(messages) > 1 else None
        responses = await self._query_references(query, flat_history, on_ref_done=on_ref_done)
        self._cache[cache_key] = responses
        return responses

    async def _query_references(
        self,
        query: str,
        chat_history: list[BaseMessage] | None,
        *,
        on_ref_done: Callable[[ReferenceResponse], Awaitable[None]] | None = None,
    ) -> list[ReferenceResponse]:
        cfg = self._cfg
        tasks = [
            asyncio.ensure_future(self._query_single(llm, query, chat_history))
            for llm in self._refs
        ]
        task_to_llm = dict(zip(tasks, self._refs, strict=True))
        ref_responses: list[ReferenceResponse] = []
        try:
            for coro in asyncio.as_completed(tasks, timeout=cfg.timeout_total):
                ref = await coro
                ref_responses.append(ref)
                if on_ref_done is not None:
                    await on_ref_done(ref)
        except TimeoutError:
            logger.warning("MoA overlay: global timeout (%.0fs)", cfg.timeout_total)
            for task in tasks:
                if not task.done():
                    task.cancel()
                    ref_responses.append(
                        ReferenceResponse(
                            model=self._model_name(task_to_llm[task]),
                            content="",
                            elapsed_seconds=cfg.timeout_total,
                            success=False,
                            error="global timeout",
                        )
                    )
        return ref_responses

    async def _query_single(
        self,
        llm: BaseChatModel,
        query: str,
        chat_history: list[BaseMessage] | None,
    ) -> ReferenceResponse:
        cfg = self._cfg
        model_name = self._model_name(llm)

        messages: list[BaseMessage] = [SystemMessage(content=ADVISOR_SYSTEM)]
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
                    if attempt < cfg.max_retries_per_model:
                        await asyncio.sleep(min(2**attempt, 30))
                        continue
                    break

                elapsed = time.monotonic() - t0
                return ReferenceResponse(
                    model=model_name,
                    content=content,
                    elapsed_seconds=elapsed,
                    success=True,
                )
            except TimeoutError:
                last_error = f"timeout ({cfg.timeout_per_model}s)"
            except Exception as exc:
                last_error = str(exc)

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

    @staticmethod
    def _model_name(llm: BaseChatModel) -> str:
        for attr in ("model_name", "model", "name"):
            val = getattr(llm, attr, None)
            if val and isinstance(val, str):
                return val
        return type(llm).__name__


def apply_privacy_to_ref(ref: ReferenceResponse, mode: PrivacyFilterMode) -> ReferenceResponse:
    if mode == "off" or not ref.content:
        return ref
    return ReferenceResponse(
        model=ref.model,
        content=_redact_for_privacy(ref.content, mode),
        elapsed_seconds=ref.elapsed_seconds,
        success=ref.success,
        error=ref.error,
    )


def sse_privacy_mode(mode: PrivacyFilterMode) -> PrivacyFilterMode:
    return mode if mode in ("display", "full") else "off"


def inject_privacy_mode(mode: PrivacyFilterMode) -> PrivacyFilterMode:
    return "full" if mode == "full" else "off"


__all__ = [
    "AdvisorFanoutRunner",
    "apply_privacy_to_ref",
    "inject_privacy_mode",
    "should_run_fanout",
    "sse_privacy_mode",
]
