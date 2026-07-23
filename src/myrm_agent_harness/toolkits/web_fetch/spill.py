"""Large web fetch output spill — head/tail preview + sandbox persistence.

Reuses UECD (Unified Evicted Content Delivery) so the product evicted-file API
and GUI drawer work without new endpoints.

Architecture: toolkits/ must not import agent/. The evicted-content helpers live
in agent.context_management.infra, so we accept them via callback injection
(set by the middleware layer at session start) rather than a static import.

[INPUT]
- utils.text_utils::smart_truncate

[OUTPUT]
- WebFetchSpillResult, maybe_spill_web_fetch_content, emit_web_fetch_evicted_ref
- set_evicted_content_callbacks (injection point for agent layer)

[POS]
Toolkit-layer delivery helper for web_fetch_tool full-content mode only.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass

from myrm_agent_harness.utils.text_utils import smart_truncate

logger = logging.getLogger(__name__)

DEFAULT_MODEL_PREVIEW_CHARS = 12_000


@dataclass(frozen=True, slots=True)
class _EvictedCallbacks:
    """Callback bundle injected by the agent layer."""

    persist: Callable[..., Awaitable[object]]
    build_footer: Callable[..., str]
    emit_ref: Callable[[str], Awaitable[None]]


_evicted_callbacks_var: ContextVar[_EvictedCallbacks | None] = ContextVar(
    "web_fetch_evicted_callbacks", default=None
)


def set_evicted_content_callbacks(
    *,
    persist_fn: Callable[..., Awaitable[object]],
    build_footer_fn: Callable[..., str],
    emit_ref_fn: Callable[[str], Awaitable[None]],
) -> None:
    """Inject evicted-content callbacks from the agent/middleware layer."""
    _evicted_callbacks_var.set(
        _EvictedCallbacks(persist=persist_fn, build_footer=build_footer_fn, emit_ref=emit_ref_fn)
    )


@dataclass(frozen=True, slots=True)
class WebFetchSpillResult:
    """Preview text returned to the model and optional GUI evicted ref."""

    preview: str
    evicted_ref: str | None = None
    spilled: bool = False


async def maybe_spill_web_fetch_content(
    content: str,
    *,
    preview_chars: int = DEFAULT_MODEL_PREVIEW_CHARS,
) -> WebFetchSpillResult:
    """Return head+tail preview; persist full text when over budget."""
    if len(content) <= preview_chars:
        return WebFetchSpillResult(preview=content, spilled=False)

    cbs = _evicted_callbacks_var.get()
    if cbs is None:
        preview = smart_truncate(content, preview_chars)
        return WebFetchSpillResult(preview=preview, spilled=True)

    persist_result = await cbs.persist(content, "web_fetch", ext="md")
    evicted_ref = persist_result.evicted_ref

    preview = smart_truncate(content, preview_chars)
    if evicted_ref and persist_result.rel_path:
        head_part = preview.split("\n\n[Truncated:")[0] if "[Truncated:" in preview else preview
        preview = f"{preview}{cbs.build_footer(evicted_basename=evicted_ref, head_text=head_part, rel_path=persist_result.rel_path)}"
    elif evicted_ref:
        preview = (
            f"{preview}\n\nFull page saved to sandbox storage. "
            "Use file_read_tool on the evicted file to read omitted sections."
        )

    return WebFetchSpillResult(preview=preview, evicted_ref=evicted_ref, spilled=True)


async def emit_web_fetch_evicted_ref(evicted_ref: str) -> None:
    """Notify the GUI that full fetch content is available in the evicted drawer."""
    cbs = _evicted_callbacks_var.get()
    if cbs is not None:
        await cbs.emit_ref(evicted_ref)
