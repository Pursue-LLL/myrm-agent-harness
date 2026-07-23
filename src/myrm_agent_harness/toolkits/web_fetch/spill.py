"""Large web fetch output spill — head/tail preview + sandbox persistence.

Reuses UECD (Unified Evicted Content Delivery) so the product evicted-file API
and GUI drawer work without new endpoints.

[INPUT]
- agent.context_management.infra.evicted_content (UECD SSOT)
- utils.text_utils::smart_truncate

[OUTPUT]
- WebFetchSpillResult, maybe_spill_web_fetch_content, emit_web_fetch_evicted_ref

[POS]
Toolkit-layer delivery helper for web_fetch_tool full-content mode only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from myrm_agent_harness.agent.context_management.infra.evicted_content import (
    build_delivery_footer,
    persist_evicted_content,
)
from myrm_agent_harness.utils.text_utils import smart_truncate

logger = logging.getLogger(__name__)

DEFAULT_MODEL_PREVIEW_CHARS = 12_000


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

    persist_result = await persist_evicted_content(content, "web_fetch", ext="md")
    evicted_ref = persist_result.evicted_ref

    preview = smart_truncate(content, preview_chars)
    if evicted_ref and persist_result.rel_path:
        head_part = preview.split("\n\n[Truncated:")[0] if "[Truncated:" in preview else preview
        preview = f"{preview}{build_delivery_footer(evicted_basename=evicted_ref, head_text=head_part, rel_path=persist_result.rel_path)}"
    elif evicted_ref:
        preview = (
            f"{preview}\n\nFull page saved to sandbox storage. "
            "Use file_read_tool on the evicted file to read omitted sections."
        )

    return WebFetchSpillResult(preview=preview, evicted_ref=evicted_ref, spilled=True)


async def emit_web_fetch_evicted_ref(evicted_ref: str) -> None:
    """Notify the GUI that full fetch content is available in the evicted drawer."""
    from myrm_agent_harness.agent.context_management.infra.evicted_content import emit_evicted_ref

    await emit_evicted_ref(evicted_ref)
