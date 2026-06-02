"""``llm_map`` agent tool factory.

Wraps the :func:`llm_map` engine (``toolkits.llms.batch``) into a LangChain tool
so the agent (and PTC scripts) can fan a single instruction over many items in
one call. Cancellation and progress are sourced implicitly from the Agent
runtime via ContextVars; oversized result sets are spilled to the Artifact Vault
and surfaced as a downloadable inline artifact so the model context never
explodes.

Layering: the pure engine lives in ``toolkits`` (no agent deps); this agent-tool
adapter — which depends on the Artifact Vault, progress sink and cancellation —
lives in ``agent.meta_tools`` to keep the toolkit layer free of reverse deps.

[INPUT]
- langchain_core.language_models::BaseChatModel (POS: chat model bound at build time)
- langchain_core.tools::tool (POS: LangChain tool decorator)
- toolkits.llms.batch.llm_map::llm_map (POS: bounded concurrent map engine)
- agent.artifacts.vault::ArtifactVault (POS: large-result spillover store)
- utils.runtime.cancellation::get_cancel_token (POS: cooperative cancellation source)
- utils.progress_sink::get_tool_progress_sink (POS: server-side progress events via ContextVar queue)

[OUTPUT]
- LlmMapInput: tool argument schema
- create_llm_map_tool(): build the ``llm_map_tool`` bound to a chat model

[POS]
``llm_map`` agent tool factory. The GUI-facing entry to the batch LLM-map
primitive.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from langchain_core.tools import tool
from pydantic import BaseModel, Field, create_model

from myrm_agent_harness.toolkits.llms.batch.llm_map import (
    DEFAULT_MAX_CONCURRENCY,
    MAX_ITEMS_HARD_CAP,
    LlmMapProgress,
    LlmMapReport,
    llm_map,
)

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)

TOOL_NAME = "llm_map_tool"
DEFAULT_MAX_ITEMS = 200
INLINE_RESULT_THRESHOLD_CHARS = 8000
PREVIEW_ITEMS = 5
PREVIEW_OUTPUT_CHARS = 280
MAX_FAILURE_SAMPLES = 10

_TOOL_DESCRIPTION = """Apply ONE instruction to MANY items in a single bounded-concurrency call.

Use this for repetitive per-item work over a list — summarise N documents,
classify/score N reviews, translate N paragraphs, extract fields from N records.
It runs each item as one cheap LLM call in parallel (NOT a sub-agent), isolates
per-item failures, emits progress events for UI rendering, and spills large
result sets to a downloadable artifact. Prefer this over a manual loop or spawning sub-agents for
homogeneous bulk tasks.

Args:
- instruction: the single directive applied to every item (kept stable for cache hits).
- items: the list of inputs; each may be inline text or a ``vault://`` pointer.
- max_concurrency: parallel calls (default 8).
- output_keys: optional field names to force a structured JSON object per item.

Returns a summary {total, succeeded, failed, cancelled} plus a preview; full
results are inlined when small or returned as a ``vault://`` artifact when large.
Do NOT use it for tasks needing cross-item reasoning, tools, or multi-step plans —
use sub-agent delegation for that.
"""


class LlmMapInput(BaseModel):
    """Argument schema for ``llm_map_tool``."""

    instruction: str = Field(
        description="The single instruction applied to EVERY item (e.g. 'Summarise in 3 bullet points')."
    )
    items: list[str] = Field(
        description="List of inputs to map over. Each item is inline text or a 'vault://' pointer to large content."
    )
    max_concurrency: int = Field(
        default=DEFAULT_MAX_CONCURRENCY,
        ge=1,
        le=32,
        description="Number of items processed in parallel (default 8).",
    )
    output_keys: list[str] | None = Field(
        default=None,
        description="Optional. Field names to force a structured JSON object per item (e.g. ['label','sentiment']).",
    )


def _build_schema(output_keys: list[str]) -> type[BaseModel]:
    """Build a per-item structured-output model from caller-supplied keys."""
    fields = {key: (str | None, None) for key in output_keys if key.isidentifier()}
    if not fields:
        raise ValueError("output_keys must contain at least one valid identifier")
    return create_model("LlmMapItemSchema", **fields)  # type: ignore[call-overload]


def _resolve_workspace_root() -> str | None:
    from myrm_agent_harness.toolkits.code_execution.utils.workspace_path import WorkspacePathResolver

    try:
        return str(WorkspacePathResolver.resolve_workspace_root())
    except Exception as exc:
        logger.debug("llm_map workspace resolution failed, results stay inline: %s", exc)
        return None


def _serialise_items(report: LlmMapReport) -> list[dict[str, object]]:
    return [
        {"index": r.index, "id": r.id, "status": r.status, "output": r.output, "error": r.error}
        for r in report.items
    ]


def _build_preview(report: LlmMapReport) -> list[dict[str, object]]:
    preview: list[dict[str, object]] = []
    for r in report.items[:PREVIEW_ITEMS]:
        out = r.output
        if isinstance(out, str) and len(out) > PREVIEW_OUTPUT_CHARS:
            out = out[:PREVIEW_OUTPUT_CHARS] + "…"
        preview.append({"id": r.id, "status": r.status, "output": out, "error": r.error})
    return preview


def _spill_results(serialised: list[dict[str, object]]) -> str | None:
    """Persist full results to the vault; return a ``vault://`` pointer or None."""
    workspace_root = _resolve_workspace_root()
    if not workspace_root:
        return None
    try:
        from myrm_agent_harness.agent.artifacts.vault import ArtifactVault

        vault = ArtifactVault(workspace_root)
        payload = json.dumps(serialised, ensure_ascii=False, indent=2)
        pointer = vault.put(
            content=payload,
            filename="llm_map_results.json",
            content_type="application/json",
            description="Batch llm_map per-item results",
        )
        try:
            from myrm_agent_harness.agent.artifacts import (
                infer_artifact_type_from_extension,
                push_inline_artifact,
            )

            push_inline_artifact(
                filename="llm_map_results.json",
                preview_url=pointer,
                artifact_type=infer_artifact_type_from_extension("llm_map_results.json"),
                content_type="application/json",
            )
        except Exception as exc:
            logger.debug("llm_map inline artifact push failed: %s", exc)
        return pointer
    except Exception as exc:
        logger.warning("llm_map vault spill failed, returning inline results: %s", exc)
        return None


def create_llm_map_tool(
    llm: BaseChatModel,
    *,
    fallback_llm: BaseChatModel | None = None,
    max_items: int = DEFAULT_MAX_ITEMS,
) -> BaseTool:
    """Build the ``llm_map_tool`` bound to *llm*.

    *llm* should be a cheap model (e.g. Haiku-class ``_extraction_llm``) since
    the fan-out can issue hundreds of calls; *fallback_llm* (typically the
    agent's primary model) backs the per-item resilient call on failover.
    """
    item_cap = max(1, min(max_items, MAX_ITEMS_HARD_CAP))

    @tool(TOOL_NAME, args_schema=LlmMapInput, description=_TOOL_DESCRIPTION)
    async def llm_map_tool(
        instruction: str,
        items: list[str],
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
        output_keys: list[str] | None = None,
    ) -> dict[str, object]:
        if not items:
            return {"success": False, "error": "items must not be empty"}

        truncated = max(0, len(items) - item_cap)
        effective = items[:item_cap]

        response_schema = _build_schema(output_keys) if output_keys else None

        from myrm_agent_harness.utils.progress_sink import get_tool_progress_sink
        from myrm_agent_harness.utils.runtime.cancellation import get_cancel_token

        sink = get_tool_progress_sink()

        async def _on_progress(p: LlmMapProgress) -> None:
            if sink is None:
                return
            await sink.emit(
                {
                    "type": "tool_progress",
                    "tool": TOOL_NAME,
                    "progress": {"done": p.done, "total": p.total, "failed": p.failed},
                }
            )

        def _resolve_vault_item(pointer: str) -> str:
            workspace_root = _resolve_workspace_root()
            if not workspace_root:
                return pointer
            from myrm_agent_harness.agent.artifacts.vault import ArtifactVault

            return ArtifactVault(workspace_root).get(pointer).decode("utf-8", errors="replace")

        report = await llm_map(
            llm,
            effective,
            instruction,
            fallback_llm=fallback_llm,
            response_schema=response_schema,
            max_concurrency=max_concurrency,
            cancel_token=get_cancel_token(),
            on_progress=_on_progress if sink is not None else None,
            item_resolver=_resolve_vault_item,
        )

        serialised = _serialise_items(report)
        summary: dict[str, object] = {
            "total": report.total,
            "succeeded": report.succeeded,
            "failed": report.failed,
            "cancelled": report.cancelled,
        }
        if truncated:
            summary["truncated"] = truncated

        result: dict[str, object] = {"success": True, "summary": summary, "preview": _build_preview(report)}
        if report.failed:
            result["failures"] = [
                {"id": r.id, "error": r.error} for r in report.items if r.status == "failed"
            ][:MAX_FAILURE_SAMPLES]

        full_json = json.dumps(serialised, ensure_ascii=False)
        if len(full_json) <= INLINE_RESULT_THRESHOLD_CHARS:
            result["results"] = serialised
        else:
            pointer = _spill_results(serialised)
            if pointer:
                result["results_vault"] = pointer
                result["note"] = "Full results stored as artifact. Use vault_get_tool / vault_extract_tool to read."
            else:
                result["results"] = serialised
        return result

    return llm_map_tool


__all__ = ["TOOL_NAME", "LlmMapInput", "create_llm_map_tool"]
