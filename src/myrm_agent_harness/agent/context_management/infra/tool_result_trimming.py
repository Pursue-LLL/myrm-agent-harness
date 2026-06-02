"""Structure-aware tool result trimming.

[INPUT]
- infra.schemas::CacheTtlPruneConfig (POS: Cache TTL prune configuration)

[OUTPUT]
- trim_tool_result_content: Trim oversized tool output while preserving useful structure.

[POS]
Tool result trimming strategy. Provides deterministic, zero-LLM compaction for cache-TTL pruning.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .schemas import CacheTtlPruneConfig

JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

_JSON_MAX_DEPTH = 4
_JSON_MAX_DICT_KEYS = 12
_JSON_MAX_LIST_ITEMS = 6
_JSON_MAX_STRING_CHARS = 400


@dataclass(frozen=True, slots=True)
class TrimmedToolResult:
    """Trimmed content and the strategy used to produce it."""

    content: str
    strategy: str


def trim_tool_result_content(
    content: str,
    config: CacheTtlPruneConfig,
) -> TrimmedToolResult | None:
    """Trim oversized tool output with a deterministic structure-first strategy."""
    max_chars = config.soft_trim_head_chars + config.soft_trim_tail_chars + 100
    if len(content) <= max_chars:
        return None

    if _should_attempt_json_trim(content, config):
        json_value = _parse_json_value(content)
        if json_value is not None:
            compacted = {
                "trimmed_tool_result": True,
                "strategy": "json_structure",
                "original_chars": len(content),
                "content": _compact_json_value(json_value, depth=0),
            }
            return TrimmedToolResult(
                content=json.dumps(compacted, ensure_ascii=False, separators=(",", ":")),
                strategy="json_structure",
            )

    return TrimmedToolResult(
        content=_trim_text_content(content, config),
        strategy="text_head_tail",
    )


def _should_attempt_json_trim(content: str, config: CacheTtlPruneConfig) -> bool:
    max_chars = max(config.large_payload_fast_guard_chars, 0)
    if max_chars > 0 and len(content) > max_chars:
        return False
    stripped = content.lstrip()
    return stripped.startswith("{") or stripped.startswith("[")


def _parse_json_value(content: str) -> JsonValue | None:
    try:
        parsed: object = json.loads(content)
    except json.JSONDecodeError:
        return None
    return _coerce_json_value(parsed)


def _coerce_json_value(value: object) -> JsonValue | None:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        coerced_list: list[JsonValue] = []
        for item in value:
            coerced = _coerce_json_value(item)
            if coerced is not None:
                coerced_list.append(coerced)
        return coerced_list
    if isinstance(value, dict):
        coerced_dict: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                continue
            coerced = _coerce_json_value(item)
            if coerced is not None:
                coerced_dict[key] = coerced
        return coerced_dict
    return str(value)


def _compact_json_value(value: JsonValue, *, depth: int) -> JsonValue:
    if depth >= _JSON_MAX_DEPTH:
        return _summarize_leaf(value)
    if isinstance(value, dict):
        return _compact_json_object(value, depth=depth)
    if isinstance(value, list):
        return _compact_json_list(value, depth=depth)
    if isinstance(value, str) and len(value) > _JSON_MAX_STRING_CHARS:
        return f"{value[:_JSON_MAX_STRING_CHARS]}... [trimmed string, original_chars={len(value)}]"
    return value


def _compact_json_object(value: dict[str, JsonValue], *, depth: int) -> JsonValue:
    items = list(value.items())
    compacted: dict[str, JsonValue] = {}
    for key, item in items[:_JSON_MAX_DICT_KEYS]:
        compacted[key] = _compact_json_value(item, depth=depth + 1)
    omitted = len(items) - len(compacted)
    if omitted > 0:
        compacted["_trimmed_keys"] = omitted
    return compacted


def _compact_json_list(value: list[JsonValue], *, depth: int) -> JsonValue:
    if len(value) <= _JSON_MAX_LIST_ITEMS:
        return [_compact_json_value(item, depth=depth + 1) for item in value]

    keep_each_side = _JSON_MAX_LIST_ITEMS // 2
    head = [_compact_json_value(item, depth=depth + 1) for item in value[:keep_each_side]]
    tail = [_compact_json_value(item, depth=depth + 1) for item in value[-keep_each_side:]]
    return {
        "trimmed_list": True,
        "original_length": len(value),
        "head": head,
        "tail": tail,
        "omitted_items": len(value) - len(head) - len(tail),
    }


def _summarize_leaf(value: JsonValue) -> JsonValue:
    if isinstance(value, dict):
        return {"trimmed_object": True, "key_count": len(value)}
    if isinstance(value, list):
        return {"trimmed_list": True, "original_length": len(value)}
    if isinstance(value, str) and len(value) > _JSON_MAX_STRING_CHARS:
        return f"{value[:_JSON_MAX_STRING_CHARS]}... [trimmed string, original_chars={len(value)}]"
    return value


def _trim_text_content(content: str, config: CacheTtlPruneConfig) -> str:
    head = content[: config.soft_trim_head_chars]
    tail = content[-config.soft_trim_tail_chars :] if config.soft_trim_tail_chars > 0 else ""
    return (
        f"{head}\n...\n{tail}"
        f"\n\n[Tool result trimmed: strategy=text_head_tail, kept first "
        f"{config.soft_trim_head_chars} and last {config.soft_trim_tail_chars} chars "
        f"of {len(content)} chars.]"
    )
