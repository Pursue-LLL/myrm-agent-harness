"""压缩内容格式化。

[INPUT]
- langchain_core.messages::AIMessage, ToolMessage (POS: LangChain 消息类型)
- schemas::CompactToolCall (POS: 压缩工具调用数据结构)

[OUTPUT]
- extract_identifier: 从工具调用中提取稳定标识符（CompactRule → 语义优先级自动回退）
- generate_compressed_content: 生成压缩格式内容
- generate_compressed_content_with_stats: 生成带统计信息的压缩内容
- generate_generic_compressed_content: 生成通用压缩格式内容（含可选 chars/lines 统计）
- shrink_tool_call_args: 对 AIMessage.tool_calls 的 args 递归缩短长字符串值，保证输出合法 JSON

[POS]
Compression formatting utilities. Provides shared formatting functions used by compactor.py and smart_fallback.py.

"""

from __future__ import annotations

from langchain_core.messages import AIMessage, ToolMessage

from myrm_agent_harness.agent.context_management.infra.schemas import CompactToolCall
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)

_SHRINK_HEAD = 200
_SHRINK_TAIL = 50
_SHRINK_MIN_LEN = 500

_IDENTIFIER_PRIORITY = ("url", "path", "query", "command", "goal", "glob_pattern", "selector", "action", "name")


def _try_extract_from_args(args: dict[str, object], key: str) -> str | None:
    val = args.get(key, "")
    if not val:
        return None
    if isinstance(val, list):
        return ", ".join(str(item) for item in val[:3])
    return str(val)[:200]


def extract_identifier(tool_msg: ToolMessage, ai_msg: AIMessage | None, identifier_arg: str) -> str:
    """从工具调用中提取稳定标识符。

    优先使用 CompactRule 指定的 identifier_arg；
    若未命中，按语义优先级自动从 url/path/query/command 等参数中提取。
    """
    matched_args: dict[str, object] | None = None

    if ai_msg and ai_msg.tool_calls:
        for tc in ai_msg.tool_calls:
            if tc.get("id") == tool_msg.tool_call_id:
                matched_args = tc.get("args", {})
                result = _try_extract_from_args(matched_args, identifier_arg)
                if result:
                    return result
                break

    if hasattr(tool_msg, "artifact") and tool_msg.artifact:
        artifact = tool_msg.artifact
        if isinstance(artifact, dict):
            result = _try_extract_from_args(artifact, identifier_arg)
            if result:
                return result

    if matched_args:
        for key in _IDENTIFIER_PRIORITY:
            result = _try_extract_from_args(matched_args, key)
            if result:
                return result

    return f"tool_call_{tool_msg.tool_call_id or 'unknown'}"


def generate_compressed_content(compact_info: CompactToolCall, template: str) -> str:
    """生成压缩格式内容。"""
    content = template.format(identifier=compact_info.identifier)
    meta = f"META: tokens_saved={compact_info.original_tokens} time={compact_info.timestamp}"
    lines = [content, meta]

    if compact_info.evicted_path:
        from myrm_agent_harness.runtime.execution_paths import PERSISTENT_ROOT

        abs_path = f"{PERSISTENT_ROOT}/{compact_info.evicted_path}"
        lines.extend(
            [
                f"FILE: {abs_path}",
                f"RECOVER: cat {abs_path}",
                "LIFECYCLE: Retained while session active (30d) or file accessed (14d)",
            ]
        )

    return "\n".join(lines)


def generate_compressed_content_with_stats(
    compact_info: CompactToolCall, stats_template: str, tool_stats: dict[str, object]
) -> str:
    """生成带统计信息的压缩内容。"""
    template_params = {
        "identifier": compact_info.identifier,
        "exit_code": tool_stats.get("exit_code", "?"),
        "lines": tool_stats.get("lines", "?"),
        "chars": tool_stats.get("chars", "?"),
        "tokens": tool_stats.get("tokens", "?"),
    }

    try:
        content = stats_template.format(**template_params)
    except KeyError as exc:
        logger.warning("[压缩] stats_template缺少参数 %s，降级到基础模板", exc)
        content = f"COMPACTED: {compact_info.tool_name}\nID: {compact_info.identifier}"

    meta = f"META: tokens_saved={compact_info.original_tokens} time={compact_info.timestamp}"
    lines = [content, meta]

    if compact_info.evicted_path:
        from myrm_agent_harness.runtime.execution_paths import PERSISTENT_ROOT

        abs_path = f"{PERSISTENT_ROOT}/{compact_info.evicted_path}"
        lines.extend(
            [
                f"FILE: {abs_path}",
                f"RECOVER: cat {abs_path}",
                "LIFECYCLE: Retained while session active (30d) or file accessed (14d)",
            ]
        )

    return "\n".join(lines)


def generate_generic_compressed_content(
    compact_info: CompactToolCall, tool_stats: dict[str, object] | None = None
) -> str:
    """生成通用压缩格式内容。"""
    lines = [
        f"COMPACTED: {compact_info.tool_name}",
        f"ID: {compact_info.identifier}",
    ]
    if tool_stats:
        chars = tool_stats.get("chars", "?")
        line_count = tool_stats.get("lines", "?")
        lines.append(f"RESULT: {chars} chars, {line_count} lines")
    lines.append(f"META: tokens_saved={compact_info.original_tokens} time={compact_info.timestamp}")

    if compact_info.evicted_path:
        from myrm_agent_harness.runtime.execution_paths import PERSISTENT_ROOT

        abs_path = f"{PERSISTENT_ROOT}/{compact_info.evicted_path}"
        lines.extend(
            [
                f"FILE: {abs_path}",
                f"RECOVER: cat {abs_path}",
                "LIFECYCLE: Retained while session active (30d) or file accessed (14d)",
            ]
        )

    return "\n".join(lines)


def _shrink_value(value: object, head: int = _SHRINK_HEAD, tail: int = _SHRINK_TAIL) -> object:
    """Recursively shrink long string values in a JSON-safe structure.

    Preserves overall structure (dicts/lists) while truncating string leaves
    that exceed _SHRINK_MIN_LEN. Keeps head+tail characters with a marker.
    """
    if isinstance(value, str):
        if len(value) <= _SHRINK_MIN_LEN:
            return value
        omitted = len(value) - head - tail
        return f"{value[:head]}…[{omitted} chars omitted]…{value[-tail:]}"

    if isinstance(value, dict):
        return {k: _shrink_value(v, head, tail) for k, v in value.items()}

    if isinstance(value, list):
        if len(value) > 20:
            shrunk = [_shrink_value(item, head, tail) for item in value[:10]]
            shrunk.append(f"…[{len(value) - 10} more items omitted]")
            return shrunk
        return [_shrink_value(item, head, tail) for item in value]

    return value


def shrink_tool_call_args(tool_calls: list[dict[str, object]]) -> list[dict[str, object]]:
    """Shrink long string values in tool_call args, preserving valid JSON structure.

    Used during context compression to prevent oversized tool_call arguments
    (e.g. full file content in file_write args) from causing API 400 errors
    when JSON is naively truncated mid-string.

    Returns a new list — does NOT mutate the original.
    """
    result: list[dict[str, object]] = []
    for tc in tool_calls:
        args = tc.get("args")
        if isinstance(args, dict):
            shrunk_args = _shrink_value(args)
            result.append({**tc, "args": shrunk_args})
        else:
            result.append(tc)
    return result
