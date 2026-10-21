"""Context pipeline middleware helper functions.

[INPUT]
- langchain.agents.middleware::ModelRequest
- context_management.infra.cache_metrics_collector::get_cache_usage_feedback
- context_management.infra.schemas::CacheUsageFeedback, CompressionIntent

[OUTPUT]
- extract_compression_intent
- resolve_cache_usage_feedback
- extract_tool_names_and_schemas
- resolve_context_budget_metadata
- estimate_request_context_tokens

[POS]
Helper layer for context pipeline middleware. Keeps request metadata parsing and tool schema
stable canonicalization separate from middleware orchestration.
"""

import json
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from langchain.agents.middleware import ModelRequest
from langchain_core.messages import BaseMessage

from myrm_agent_harness.agent.context_management.infra.cache_metrics_collector import (
    get_cache_usage_feedback,
)
from myrm_agent_harness.agent.context_management.infra.schemas import (
    CacheUsageFeedback,
    CompressionIntent,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.token_estimation import (
    estimate_context_tokens,
    estimate_request_tools_tokens,
)

if TYPE_CHECKING:
    from myrm_agent_harness.agent.context_management.infra.schemas import SummaryPersistCallback
    from myrm_agent_harness.agent.context_management.pipeline import ProcessorContext

logger = get_agent_logger(__name__)


def extract_compression_intent(
    merged_ctx: dict[str, object],
) -> dict[str, object] | None:
    """Extract structured compression intent from merged_context."""
    intent = CompressionIntent.from_object(merged_ctx.get("compression_intent"))
    return intent.to_dict() if intent is not None else None


def resolve_cache_usage_feedback(
    merged_ctx: dict[str, object],
) -> CacheUsageFeedback | None:
    """Prefer explicit business metadata, then provider usage collected in harness."""
    explicit = CacheUsageFeedback.from_mapping(
        {
            "cache_hit_rate": merged_ctx.get("cache_hit_rate"),
            "cached_tokens": merged_ctx.get("cached_tokens"),
            "input_tokens": merged_ctx.get("input_tokens"),
            "calls": merged_ctx.get("cache_feedback_calls"),
        }
    )
    return explicit or get_cache_usage_feedback()


def resolve_context_budget_metadata(request: ModelRequest) -> dict[str, int]:
    """Extract bind-tools overhead and last provider prompt_tokens for compress budget."""
    from myrm_agent_harness.utils.token_economics.tracker import get_token_tracker

    metadata: dict[str, int] = {}
    tools = getattr(request, "tools", None)
    if isinstance(tools, list | tuple) and tools:
        metadata["bound_tool_overhead_tokens"] = estimate_request_tools_tokens(tools)

    tracker = get_token_tracker()
    if tracker is not None and tracker.usage.last_call is not None:
        prompt_tokens = tracker.usage.last_call.prompt_tokens
        if prompt_tokens > 0:
            metadata["last_provider_prompt_tokens"] = prompt_tokens
    return metadata


def estimate_request_context_tokens(
    messages: list[BaseMessage],
    request: ModelRequest,
) -> int:
    """Full request context estimate for pipeline preflight checks."""
    budget_meta = resolve_context_budget_metadata(request)
    return estimate_context_tokens(
        messages,
        bound_tool_overhead_tokens=budget_meta.get("bound_tool_overhead_tokens", 0),
        last_provider_prompt_tokens=budget_meta.get("last_provider_prompt_tokens"),
    )


def extract_tool_names_and_schemas(
    request: ModelRequest,
) -> list[tuple[str, str]] | None:
    """Extract stable tool schema fingerprints from the active model request."""
    tools = getattr(request, "tools", None)
    if not isinstance(tools, list | tuple) or not tools:
        return None

    extracted: list[tuple[str, str]] = []
    for tool in tools:
        name = _tool_name(tool)
        if not name:
            continue
        extracted.append((name, _tool_schema_text(tool)))

    return extracted or None


def _tool_name(tool: object) -> str:
    if isinstance(tool, dict):
        value = tool.get("name")
        if isinstance(value, str):
            return value
    value = getattr(tool, "name", "")
    return value if isinstance(value, str) else ""


def _tool_schema_text(tool: object) -> str:
    if isinstance(tool, dict):
        return _canonical_json(tool)

    schema = getattr(tool, "args_schema", None)
    if schema is not None and hasattr(schema, "model_json_schema"):
        model_json_schema = schema.model_json_schema
        if callable(model_json_schema):
            payload = model_json_schema()
            return _canonical_json(payload)

    tool_call_schema = getattr(tool, "tool_call_schema", None)
    if tool_call_schema is not None:
        return _canonical_json(tool_call_schema)

    payload = {
        "description": getattr(tool, "description", ""),
        "args": getattr(tool, "args", None),
    }
    return _canonical_json(payload)


def _canonical_json(value: object) -> str:
    return json.dumps(_to_json_safe(value), ensure_ascii=False, sort_keys=True)


def _to_json_safe(value: object) -> object:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Mapping):
        return {str(key): _to_json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_to_json_safe(item) for item in value]
    if isinstance(value, type):
        return {"type": value.__qualname__}
    return {"type": type(value).__qualname__}


__all__ = [
    "estimate_request_context_tokens",
    "extract_compression_intent",
    "extract_tool_names_and_schemas",
    "resolve_cache_usage_feedback",
    "resolve_context_budget_metadata",
]


def count_tool_calls(messages: Sequence[BaseMessage]) -> int:
    """Count total tool calls across all messages."""
    count = 0
    for msg in messages:
        if msg.type == "ai" and getattr(msg, "tool_calls", None):
            count += len(msg.tool_calls)
    return count


def extract_last_message_db_id(request: ModelRequest) -> str | None:
    """Extract the last message DB id from the request runtime context."""
    try:
        if not hasattr(request, "runtime") or not request.runtime:
            return None
        context = getattr(request.runtime, "context", None)
        if isinstance(context, dict):
            val = context.get("last_message_db_id")
        else:
            val = getattr(context, "last_message_db_id", None)
        return str(val) if val is not None else None
    except Exception:
        return None


async def safe_persist_summary(
    callback: "SummaryPersistCallback",
    chat_id: str,
    result: "ProcessorContext",
) -> None:
    """Safely invoke the summary persist callback (fire-and-forget, non-blocking)."""
    try:
        await callback(
            chat_id=chat_id,
            summary=result.structured_summary,  # type: ignore[arg-type]
            before_message_id=result.last_summarized_message_id or "",
            tokens_saved=result.tokens_saved,
        )
        logger.info(
            "[SummaryPersist] Summary persisted: chat_id=%s, tokens_saved=%d",
            chat_id,
            result.tokens_saved,
        )
    except Exception as exc:
        logger.error("[SummaryPersist] Persist failed: %s", exc)
