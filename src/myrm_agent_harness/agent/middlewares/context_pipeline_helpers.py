"""Context pipeline middleware helper functions.

[INPUT]
- langchain.agents.middleware::ModelRequest
- context_management.infra.cache_metrics_collector::get_cache_usage_feedback
- context_management.infra.schemas::CacheUsageFeedback, CompressionIntent

[OUTPUT]
- extract_compression_intent
- resolve_cache_usage_feedback
- extract_tool_names_and_schemas

[POS]
Helper layer for context pipeline middleware. Keeps request metadata parsing and tool schema
stable canonicalization separate from middleware orchestration.
"""

import json
from collections.abc import Mapping, Sequence

from langchain.agents.middleware import ModelRequest

from myrm_agent_harness.agent.context_management.infra.cache_metrics_collector import (
    get_cache_usage_feedback,
)
from myrm_agent_harness.agent.context_management.infra.schemas import (
    CacheUsageFeedback,
    CompressionIntent,
)


def extract_compression_intent(
    merged_ctx: dict[str, object],
) -> dict[str, object] | None:
    """Extract structured compression intent from merged_context."""
    intent = CompressionIntent.from_object(merged_ctx.get("compression_intent"))
    return intent.to_dict() if intent is not None else None


def resolve_cache_usage_feedback(merged_ctx: dict[str, object]) -> CacheUsageFeedback | None:
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


def extract_tool_names_and_schemas(request: ModelRequest) -> list[tuple[str, str]] | None:
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
    "extract_compression_intent",
    "extract_tool_names_and_schemas",
    "resolve_cache_usage_feedback",
]
