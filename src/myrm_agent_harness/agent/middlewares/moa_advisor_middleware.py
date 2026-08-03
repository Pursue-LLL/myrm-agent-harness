"""Agent-loop MoA advisor overlay middleware.

Runs lightweight reference-model fan-out before each acting-model call (per
fanout policy), emits SSE progress events, and injects advisor perspectives
into the last HumanMessage tail without persisting to checkpoint history.

[INPUT]
- toolkits.llms.consensus.advisor_fanout::AdvisorFanoutRunner
- toolkits.llms.consensus.advisor_prompts::build_advisor_injection_block
- agent.middlewares.goal_focus_middleware helpers for HumanMessage append
- utils.runtime.progress_sink::get_tool_progress_sink

[OUTPUT]
- create_moa_advisor_middleware(): factory returning wrap_model_call middleware

[POS]
Transient advisor injection for agent tool loops. Mount after context_pipeline
(server factory) so compression runs before fan-out. Skips unattended runs,
budget pressure (emits moa_overlay_skipped when fan-out would run), and when
overlay is disabled.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware import ModelRequest, ModelResponse, wrap_model_call

from myrm_agent_harness.agent.middlewares.goal_focus_middleware import (
    _append_to_last_human_message,
)
from myrm_agent_harness.toolkits.llms.consensus.advisor_fanout import (
    AdvisorFanoutRunner,
    apply_privacy_to_ref,
    inject_privacy_mode,
    should_run_fanout,
    sse_privacy_mode,
)
from myrm_agent_harness.toolkits.llms.consensus.advisor_prompts import (
    build_advisor_injection_block,
)
from myrm_agent_harness.toolkits.llms.consensus.moa_overlay_types import (
    MoAOverlayConfig,
    PrivacyFilterMode,
)
from myrm_agent_harness.toolkits.llms.consensus.types import ReferenceResponse

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)

MOA_OVERLAY_SKIP_BUDGET_PRESSURE = "budget_pressure"
MOA_OVERLAY_SKIP_INSUFFICIENT_REFS = "insufficient_refs"

_moa_budget_skip_notified_var: ContextVar[bool] = ContextVar(
    "moa_budget_skip_notified", default=False
)


def _budget_pressure_active() -> bool:
    try:
        from myrm_agent_harness.utils.token_economics.tracker import get_token_tracker

        tracker = get_token_tracker()
        if tracker is None:
            return False
        status = getattr(tracker, "last_budget_status", "ok")
        return status not in ("ok", "")
    except Exception:
        return False


async def _emit_ref_done(
    ref_model: str, *, success: bool, elapsed: float, content: str | None
) -> None:
    from myrm_agent_harness.utils.runtime.progress_sink import get_tool_progress_sink

    sink = get_tool_progress_sink()
    if sink is None:
        return
    await sink.emit(
        {
            "type": "status",
            "step_key": "moa_ref_done",
            "data": {
                "model": ref_model,
                "success": success,
                "elapsed": elapsed,
                "content": content,
            },
        }
    )


async def _emit_overlay_active(reference_models: list[str]) -> None:
    from myrm_agent_harness.utils.runtime.progress_sink import get_tool_progress_sink

    sink = get_tool_progress_sink()
    if sink is None:
        return
    await sink.emit(
        {
            "type": "status",
            "step_key": "moa_overlay_active",
            "data": {"reference_models": reference_models},
        }
    )


async def _emit_overlay_skipped(reason: str) -> None:
    from myrm_agent_harness.utils.runtime.progress_sink import get_tool_progress_sink

    sink = get_tool_progress_sink()
    if sink is None:
        return
    await sink.emit(
        {
            "type": "status",
            "step_key": "moa_overlay_skipped",
            "status": "warning",
            "data": {"reason": reason},
        }
    )


def _model_name(llm: BaseChatModel) -> str:
    for attr in ("model_name", "model", "name"):
        val = getattr(llm, attr, None)
        if val and isinstance(val, str):
            return val
    return type(llm).__name__


def create_moa_advisor_middleware(
    reference_llms: list[BaseChatModel],
    *,
    config: MoAOverlayConfig | None = None,
    unattended: bool = False,
) -> Any:
    """Build MoA advisor overlay middleware bound to pre-resolved reference LLMs."""
    overlay_cfg = config or MoAOverlayConfig()
    runner = AdvisorFanoutRunner(reference_llms, overlay_cfg)
    privacy_mode: PrivacyFilterMode = overlay_cfg.privacy_filter

    @wrap_model_call(name="moa_advisor_middleware")  # type: ignore[arg-type]
    async def _middleware(
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        if unattended:
            return await handler(request)

        messages = list(request.messages)
        next_iteration = runner.iteration + 1
        fanout_this_call = should_run_fanout(
            messages=messages,
            fanout=overlay_cfg.fanout,
            every_n=overlay_cfg.every_n,
            iteration=next_iteration,
        )

        if _budget_pressure_active():
            if fanout_this_call and not _moa_budget_skip_notified_var.get():
                await _emit_overlay_skipped(MOA_OVERLAY_SKIP_BUDGET_PRESSURE)
                _moa_budget_skip_notified_var.set(True)
            logger.debug("MoA overlay skipped: budget pressure active")
            return await handler(request)

        if fanout_this_call:
            ref_names = [_model_name(llm) for llm in reference_llms]
            await _emit_overlay_active(ref_names)

        async def _on_ref_done(ref: ReferenceResponse) -> None:
            sse_ref = apply_privacy_to_ref(ref, sse_privacy_mode(privacy_mode))
            await _emit_ref_done(
                sse_ref.model,
                success=sse_ref.success,
                elapsed=sse_ref.elapsed_seconds,
                content=sse_ref.content if sse_ref.success else None,
            )

        ref_responses = await runner.run(messages, on_ref_done=_on_ref_done)
        if not ref_responses:
            return await handler(request)

        successful = [r for r in ref_responses if r.success and r.content.strip()]
        if len(successful) < overlay_cfg.min_successful:
            if fanout_this_call:
                await _emit_overlay_skipped(MOA_OVERLAY_SKIP_INSUFFICIENT_REFS)
            logger.info(
                "MoA overlay: insufficient refs (%d/%d), skipping injection",
                len(successful),
                overlay_cfg.min_successful,
            )
            return await handler(request)

        inject_refs = [
            apply_privacy_to_ref(r, inject_privacy_mode(privacy_mode))
            for r in successful
        ]
        injection = build_advisor_injection_block(inject_refs)
        if not injection:
            return await handler(request)

        new_messages = _append_to_last_human_message(messages, injection)
        return await handler(request.override(messages=new_messages))

    return _middleware


__all__ = [
    "MOA_OVERLAY_SKIP_BUDGET_PRESSURE",
    "MOA_OVERLAY_SKIP_INSUFFICIENT_REFS",
    "create_moa_advisor_middleware",
]
