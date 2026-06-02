"""Summary parsing — extract and parse StructuredSummary from messages/LLM responses.

[INPUT]
- schemas::StructuredSummary (POS: structured summary dataclass)
- langchain_core.messages::BaseMessage (POS: LangChain message base class)
- security.detection.leak_detector::redact_leaks (POS: 输出侧凭证泄露检测器)

[OUTPUT]
- extract_existing_summary: detect existing summary in message list
- format_messages_for_summary: convert messages to text for LLM summarisation (with credential redaction)
- extract_messages_after_summary: slice messages after summary marker
- parse_summary_response: parse StructuredSummary from raw LLM JSON / mixed text

[POS]
Summary parsing and message formatting utilities.
format_messages_for_summary applies credential redaction before sending to summarisation LLM.
"""

from __future__ import annotations

import json
import re

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from myrm_agent_harness.agent.security.detection.leak_detector import redact_leaks
from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.text_utils import smart_truncate

from ..infra.schemas import StructuredSummary

logger = get_agent_logger(__name__)


_SUMMARY_MARKERS = ("[历史摘要]", "[Previous conversation summary]")


def extract_existing_summary(messages: list[BaseMessage]) -> StructuredSummary | None:
    """从消息列表中提取已有摘要

    检测任意消息中以摘要标记开头的内容（不依赖消息类型）。
    Pipeline 产生的摘要以 [历史摘要] 开头（HumanMessage），
    /compact 或持久化回写的摘要以 [Previous conversation summary] 开头（assistant 角色）。
    """
    for msg in messages:
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        if any(content.startswith(marker) for marker in _SUMMARY_MARKERS):
            return _parse_summary_from_message(content)
    return None


def extract_messages_after_summary(messages: list[BaseMessage]) -> list[BaseMessage]:
    """提取摘要消息之后的新消息

    用于增量合并模式，只处理摘要之后的新内容。
    兼容两种标记：[历史摘要]（Pipeline 产生）和 [Previous conversation summary]（持久化回写）。
    """
    summary_index = -1

    for i, msg in enumerate(messages):
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        if any(content.startswith(marker) for marker in _SUMMARY_MARKERS):
            summary_index = i
            break

    if summary_index >= 0:
        return messages[summary_index + 1 :]
    return messages


def format_messages_for_summary(messages: list[BaseMessage]) -> str:
    """格式化消息用于摘要生成（完整格式，非紧凑格式）。"""
    formatted_parts = []

    for msg in messages:
        if isinstance(msg, HumanMessage):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            formatted_parts.append(f"[用户] {content[:500]}...")
        elif isinstance(msg, AIMessage):
            if msg.tool_calls:
                tool_names = [tc.get("name", "unknown") for tc in msg.tool_calls]
                formatted_parts.append(f"[AI 调用工具] {', '.join(tool_names)}")
            elif msg.content:
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                formatted_parts.append(f"[AI 回复] {content[:500]}...")
        elif isinstance(msg, ToolMessage):
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            formatted_parts.append(f"[工具结果: {msg.name}] {smart_truncate(content, 1000)}")
        elif isinstance(msg, SystemMessage):
            pass

    return redact_leaks("\n\n".join(formatted_parts))


# ---------------------------------------------------------------------------
# Shared dict → StructuredSummary builder
# ---------------------------------------------------------------------------


def _build_summary_from_dict(data: dict[str, object], context_dump_path: str = "") -> StructuredSummary:
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
        constraints_and_preferences=_as_str_list(data.get("constraints_and_preferences")),
        resolved_questions=_as_str_list(data.get("resolved_questions")),
        pending_user_asks=_as_str_list(data.get("pending_user_asks")),
        active_state=str(data.get("active_state", "")),
    )


def parse_summary_response(response: object, context_dump_path: str = "") -> StructuredSummary:
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


def _extract_summary_dict_from_llm_text(text: str) -> dict[str, object] | None:
    stripped = text.strip()
    direct = _try_json_load_dict(stripped)
    if direct is not None:
        return direct
    tag = re.search(r"<summary>(.*?)</summary>", stripped, re.DOTALL | re.IGNORECASE)
    if tag:
        inner = tag.group(1).strip()
        tagged = _try_json_load_decor(inner)
        if tagged is not None:
            return tagged
    return _scan_json_objects_for_dict(stripped)


def _try_json_load_decor(inner: str) -> dict[str, object] | None:
    parsed = _try_json_load_dict(inner)
    if parsed is not None:
        return parsed
    return _scan_json_objects_for_dict(inner)


def _scan_json_objects_for_dict(text: str) -> dict[str, object] | None:
    start = text.find("{")
    while start != -1:
        try:
            obj, _end = json.JSONDecoder().raw_decode(text, start)
        except json.JSONDecodeError:
            start = text.find("{", start + 1)
            continue
        if isinstance(obj, dict):
            return obj
        start = text.find("{", start + 1)
    return None


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
    """从摘要消息内容中解析 StructuredSummary

    优先使用嵌入的 JSON 块（更可靠），如果没有则回退到文本解析。
    """
    json_summary = _parse_summary_from_json_block(content)
    if json_summary:
        return json_summary
    return _parse_summary_from_text(content)


def _parse_summary_from_json_block(content: str) -> StructuredSummary | None:
    """从嵌入的 JSON 块解析摘要

    JSON 块格式：
    <!-- SUMMARY_JSON
    {...}
    -->
    """
    try:
        start_marker = "<!-- SUMMARY_JSON"
        end_marker = "-->"

        start_idx = content.find(start_marker)
        if start_idx == -1:
            return None

        json_start = content.find("\n", start_idx) + 1
        end_idx = content.find(end_marker, json_start)
        if end_idx == -1:
            return None

        json_str = content[json_start:end_idx].strip()
        data = json.loads(json_str)
        return _build_summary_from_dict(data)
    except Exception:
        return None


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
            for ch in "\U0001f3af\U0001f4cc\U0001f4cd\u2699\ufe0f\u2705\U0001f4a1\u26a0\ufe0f\U0001f534\U0001f527":
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
