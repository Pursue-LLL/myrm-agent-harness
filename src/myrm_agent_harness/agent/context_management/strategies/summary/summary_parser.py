"""Summary parsing — extract and parse StructuredSummary from messages/LLM responses.

[INPUT]
- schemas::StructuredSummary (POS: structured summary dataclass)
- langchain_core.messages::BaseMessage (POS: LangChain message base class)
- security.detection.leak_detector::redact_leaks (POS: 输出侧凭证泄露检测器)
- utils.json_parsing::parse_llm_json_object (POS: robust JSON object extraction from LLM output — fences, prose, bare control chars, trailing commas; requires the ``user_goal`` key for summary-message scan)

[OUTPUT]
- extract_existing_summary: detect existing summary in message list
- is_summary_message: detect whether a message is a context summary block
- format_messages_for_summary: convert messages to text for LLM summarisation (with credential redaction)
- extract_messages_after_summary: slice messages after summary marker
- parse_summary_response: parse StructuredSummary from raw LLM JSON / mixed text
- parse_structured_summary_json: parse StructuredSummary from strict JSON string (None on failure; shared by server persistence boundary)

[POS]
Summary parsing and message formatting utilities.
format_messages_for_summary applies credential redaction before sending to summarisation LLM.
"""

from __future__ import annotations

import json

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from myrm_agent_harness.agent.security.detection.leak_detector import redact_leaks
from myrm_agent_harness.utils.json_parsing import parse_llm_json_object
from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.text_utils import smart_truncate

from ...infra.schemas import StructuredSummary

logger = get_agent_logger(__name__)


_SUMMARY_JSON_MARKER = "<!-- SUMMARY_JSON"
_LEGACY_TEXT_MARKERS = ("[历史摘要]", "[Previous conversation summary]")


def _is_summary_message(content: str) -> bool:
    """Check whether a message contains a summary (JSON block or legacy text prefix)."""
    if _SUMMARY_JSON_MARKER in content:
        return True
    return any(content.startswith(marker) for marker in _LEGACY_TEXT_MARKERS)


def is_summary_message(msg: BaseMessage) -> bool:
    """Detect whether a message is a context summary block.

    Matches both pipeline-generated summaries (``HumanMessage`` from
    ``create_summary_message``, which embeds a ``<!-- SUMMARY_JSON`` block) and
    server-injected legacy summaries (``[历史摘要]`` / ``[Previous conversation
    summary]`` prefix). Shared by message-reconstruction paths so stale summary
    blocks never survive a compaction rebuild.
    """
    content = msg.content if isinstance(msg.content, str) else str(msg.content)
    return _is_summary_message(content)


def extract_existing_summary(messages: list[BaseMessage]) -> StructuredSummary | None:
    """从消息列表中提取最新摘要（最后一个可解析摘要块）。

    优先检测 ``<!-- SUMMARY_JSON`` 嵌入块（Pipeline 产生的摘要以 ``<memory-context>``
    开头，内含此 JSON 块）。回退到 legacy 文本前缀检测（``[历史摘要]`` /
    ``[Previous conversation summary]``）以兼容持久化回写的旧格式摘要。

    压缩重建总是把新摘要块放在消息列表的尾部位置（``create_summary_message``
    置于 protected_head 之后、recent_messages 之前），因此消息位置即时间顺序：
    反向遍历取最后一个可解析块 = 最新摘要。多块残留场景（修复前的历史会话）下
    避免增量合并以旧摘要为基准，导致新摘要信息丢失。
    """
    for msg in reversed(messages):
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        if _is_summary_message(content):
            parsed = _parse_summary_from_message(content)
            if parsed is not None:
                return parsed
    return None


def extract_messages_after_summary(messages: list[BaseMessage]) -> list[BaseMessage]:
    """提取最新摘要块之后的新消息（用于增量合并模式）。

    与 ``extract_existing_summary`` 定位同一个（最后一个可解析）摘要块作为锚点，
    保证增量合并输入与 ``existing_summary`` 对齐——锚点之前的内容已并入该摘要，
    不重复合并。同时剔除切片结果中残留的孤儿摘要块，避免旧压缩块进入增量合并输入。
    """
    for i in range(len(messages) - 1, -1, -1):
        content = messages[i].content if isinstance(messages[i].content, str) else str(messages[i].content)
        if _is_summary_message(content) and _parse_summary_from_message(content) is not None:
            return [m for m in messages[i + 1 :] if not is_summary_message(m)]
    return [m for m in messages if not is_summary_message(m)]


def format_messages_for_summary(messages: list[BaseMessage]) -> str:
    """格式化消息用于摘要生成（完整格式，非紧凑格式）。"""
    formatted_parts = []

    for msg in messages:
        if is_summary_message(msg):
            continue
        if isinstance(msg, HumanMessage):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            formatted_parts.append(f"[用户] {content[:500]}...")
        elif isinstance(msg, AIMessage):
            if msg.tool_calls:
                tool_names = [tc.get("name", "unknown") for tc in msg.tool_calls]
                formatted_parts.append(f"[AI 调用工具] {', '.join(tool_names)}")
            elif msg.content:
                content = (
                    msg.content if isinstance(msg.content, str) else str(msg.content)
                )
                formatted_parts.append(f"[AI 回复] {content[:500]}...")
        elif isinstance(msg, ToolMessage):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            formatted_parts.append(
                f"[工具结果: {msg.name}] {smart_truncate(content, 1000)}"
            )
        elif isinstance(msg, SystemMessage):
            pass

    return redact_leaks("\n\n".join(formatted_parts))


# ---------------------------------------------------------------------------
# Shared dict → StructuredSummary builder
# ---------------------------------------------------------------------------


def _build_summary_from_dict(
    data: dict[str, object], context_dump_path: str = ""
) -> StructuredSummary:
    """从 JSON dict 构建 StructuredSummary，统一所有解析路径的字段映射。"""
    return StructuredSummary(
        user_goal=str(data.get("user_goal", "未知目标")),
        completed_actions=_as_str_list(data.get("completed_actions")),
        key_findings=_as_str_list(data.get("key_findings")),
        errors_and_fixes=_as_str_list(data.get("errors_and_fixes")),
        files_modified=_as_str_list(data.get("files_modified")),
        last_action=str(data.get("last_action", "")),
        context_dump_path=context_dump_path or str(data.get("context_dump_path", "")),
        active_task=str(data.get("active_task", "")),
        constraints_and_preferences=_as_str_list(
            data.get("constraints_and_preferences")
        ),
        resolved_questions=_as_str_list(data.get("resolved_questions")),
        pending_user_asks=_as_str_list(data.get("pending_user_asks")),
        active_state=str(data.get("active_state", "")),
        blocked_items=_as_str_list(data.get("blocked_items")),
        next_steps=_as_str_list(data.get("next_steps")),
    )


def parse_summary_response(
    response: object, context_dump_path: str = ""
) -> StructuredSummary:
    """Parse ``StructuredSummary`` from an LLM response body (JSON string, tagged block, or mixed text)."""
    if isinstance(response, list):
        return _build_summary_from_dict({}, context_dump_path=context_dump_path)

    text = response if isinstance(response, str) else str(response)
    data = _extract_summary_dict_from_llm_text(text)
    if data is None:
        return StructuredSummary(user_goal="[摘要解析失败]", key_findings=[text])
    return _build_summary_from_dict(data, context_dump_path=context_dump_path)


def _try_json_load_dict(raw: str) -> dict[str, object] | None:
    try:
        val = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(val, dict):
        return val
    return None


def parse_structured_summary_json(summary_json: str) -> StructuredSummary | None:
    """从严格 JSON 字符串解析 StructuredSummary（失败返回 None）。

    与 ``parse_summary_response``（容错解析 LLM 输出）不同，本函数仅接受
    已序列化的 JSON 文本（如 ``StructuredSummary.to_json`` 产物或 DB 持久化
    的 ``compacted_summary``），解析失败返回 None 而非占位摘要——调用方据此
    走 full 模式而不是用残破基准做增量合并。字段映射统一走
    ``_build_summary_from_dict``，保证跨持久化边界的字段完整性。
    """
    data = _try_json_load_dict(summary_json)
    if data is None:
        return None
    return _build_summary_from_dict(data)


def _extract_summary_dict_from_llm_text(text: str) -> dict[str, object] | None:
    return parse_llm_json_object(text)


def _as_str_list(val: object) -> list[str]:
    """安全地将值转换为 list[str]，容忍 None 和非列表类型。"""
    if val is None:
        return []
    if isinstance(val, list):
        return [str(item) for item in val]
    return [str(val)]


# ---------------------------------------------------------------------------
# Internal parsing helpers
# ---------------------------------------------------------------------------


def _parse_summary_from_message(content: str) -> StructuredSummary | None:
    """从摘要消息内容中解析 StructuredSummary。

    三级回退：
    1. ``<!-- SUMMARY_JSON`` 嵌入块（Pipeline 产生，最可靠）
    2. robust JSON object 提取（覆盖 server 注入的 ``[Previous conversation summary]\\n{JSON}`` 格式，含尾逗号/裸换行/散文包裹）
    3. 中文行标签文本解析（最后回退）
    """
    json_summary = _parse_summary_from_json_block(content)
    if json_summary:
        return json_summary
    raw_dict = parse_llm_json_object(content, require_key="user_goal")
    if raw_dict is not None:
        return _build_summary_from_dict(raw_dict)
    return _parse_summary_from_text(content)


def _parse_summary_from_json_block(content: str) -> StructuredSummary | None:
    """从嵌入的 JSON 块解析摘要

    JSON 块格式：
    <!-- SUMMARY_JSON
    {...}
    -->
    """
    start_marker = "<!-- SUMMARY_JSON"
    end_marker = "-->"

    start_idx = content.find(start_marker)
    if start_idx == -1:
        return None

    json_start = content.find("\n", start_idx) + 1

    # JSON 值可能包含字面 "-->"（如 markdown 箭头、代码片段），逐个尝试闭合
    # 标记直到 JSON 解析成功；正常块首次即命中，无额外开销。
    search_from = json_start
    while True:
        end_idx = content.find(end_marker, search_from)
        if end_idx == -1:
            return None
        data = _try_json_load_dict(content[json_start:end_idx].strip())
        if data is not None:
            return _build_summary_from_dict(data)
        search_from = end_idx + len(end_marker)


def _parse_summary_from_text(content: str) -> StructuredSummary | None:
    """从文本格式解析摘要（兼容新旧格式）。"""
    try:
        user_goal = ""
        active_task = ""
        active_state = ""
        completed_actions: list[str] = []
        key_findings: list[str] = []
        errors_and_fixes: list[str] = []
        files_modified: list[str] = []
        constraints_and_preferences: list[str] = []
        resolved_questions: list[str] = []
        pending_user_asks: list[str] = []
        last_action = ""
        context_dump_path = ""

        section_map: dict[str, str] = {
            "已完成操作:": "completed",
            "关键发现:": "findings",
            "错误与修复:": "errors",
            "错误和修复:": "errors",
            "修改的文件:": "files",
            "[Artifact 索引]": "files",
            "用户约束与偏好:": "constraints",
            "已回答的问题:": "resolved",
            "待完成请求:": "pending",
        }

        list_targets: dict[str, list[str]] = {
            "completed": completed_actions,
            "findings": key_findings,
            "errors": errors_and_fixes,
            "files": files_modified,
            "constraints": constraints_and_preferences,
            "resolved": resolved_questions,
            "pending": pending_user_asks,
        }

        lines = content.split("\n")
        current_section = ""

        for line in lines:
            stripped = line.strip()
            # strip emoji prefixes for section header matching
            clean = stripped
            for (
                ch
            ) in "\U0001f3af\U0001f4cc\U0001f4cd\u2699\ufe0f\u2705\U0001f4a1\u26a0\ufe0f\U0001f534\U0001f527":
                clean = clean.lstrip(ch)
            clean = clean.lstrip(" ")

            if clean.startswith("用户目标:"):
                user_goal = clean[len("用户目标:") :].strip()
            elif clean.startswith("当前任务:"):
                active_task = clean[len("当前任务:") :].strip()
            elif clean.startswith("最后操作:"):
                last_action = clean[len("最后操作:") :].strip()
                current_section = ""
            elif clean.startswith("工作状态:"):
                active_state = clean[len("工作状态:") :].strip()
            elif clean.startswith("路径:") or clean.startswith("历史日志:"):
                prefix = "路径:" if clean.startswith("路径:") else "历史日志:"
                context_dump_path = clean[len(prefix) :].strip()
            elif clean in section_map:
                current_section = section_map[clean]
            elif stripped.startswith("- ") or stripped.startswith("  - "):
                item = stripped.lstrip("- ").strip()
                target = list_targets.get(current_section)
                if target is not None:
                    target.append(item)

        if user_goal:
            return StructuredSummary(
                user_goal=user_goal,
                completed_actions=completed_actions,
                key_findings=key_findings,
                errors_and_fixes=errors_and_fixes,
                files_modified=files_modified,
                last_action=last_action,
                context_dump_path=context_dump_path,
                active_task=active_task,
                constraints_and_preferences=constraints_and_preferences,
                resolved_questions=resolved_questions,
                pending_user_asks=pending_user_asks,
                active_state=active_state,
            )
    except Exception:
        pass

    return None
