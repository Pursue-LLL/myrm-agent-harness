"""聊天工具函数模块（通用部分）

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- langchain_core.messages::BaseMessage, AIMessage, HumanMessage (POS: LangChain 消息类型)
- utils.text_sanitizer::extract_and_strip_think_blocks (POS: 剥离内联 think/reasoning 标签块)

[OUTPUT]
- ChatHistory, ContentItem, ChatHistoryReq: 聊天历史相关类型定义
- convert_chat_history_simple(): 将聊天历史转换为 LangChain 消息格式（仅文本）
- extract_text_content(): 从字符串 / 多媒体列表 / JSON 中提取纯文本
- extract_answer_text(): 从 LLM 响应提取用户可见答案文本（str / block list / think 剥离 / reasoning 模型回退）
- extract_litellm_answer_text(): 从 litellm 原生响应提取用户可见答案文本（choices[0].message / reasoning_content / block list）
- parse_llm_json_object() / parse_llm_json_list(): 从 LLM 回复中容错提取 JSON 对象 / 数组（fence / prose / 裸控制字符 / 尾逗号 / 多候选取末）；parse_llm_json_object 支持 require_key 过滤（仅取含指定键的对象）

[POS]
Chat utility functions. Provides business-config-independent chat history conversion (generic part).

"""

import json
import logging
import re
from collections.abc import Iterable
from typing import Literal, cast

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from myrm_agent_harness.utils.text_sanitizer import extract_and_strip_think_blocks

logger = logging.getLogger(__name__)

ChatHistory = list[BaseMessage]

ContentItem = str | list[dict[str, object]]
# entry 格式: [role, content] 或 [role, content, metadata_dict]
ChatHistoryEntry = list[Literal["human", "assistant"] | ContentItem | dict[str, object]]
ChatHistoryReq = list[ChatHistoryEntry]


def convert_chat_history_simple(history: object) -> ChatHistory:
    """将聊天历史转换为LangChain消息格式，仅处理文本内容，智能判断输入格式

    用于查询改写等不需要处理图片的场景。
    对 __agent_history JSON 格式的 assistant 消息，只提取 content 文本。

    Args:
        history: 原始格式或已转换格式
    """
    if not history:
        return []

    if isinstance(history, list) and history and isinstance(history[0], BaseMessage):
        return history

    entries = cast("list[ChatHistoryEntry]", history)
    messages: list[BaseMessage] = []
    for item in entries:
        role, content = item[0], item[1]
        meta = item[2] if len(item) > 2 and isinstance(item[2], dict) else {}

        text_content = extract_text_content(cast("ContentItem", content))

        if role == "human":
            messages.append(HumanMessage(content=text_content))
        else:
            additional_kwargs: dict[str, object] = {}
            reasoning_content = meta.get("reasoning_content")
            if isinstance(reasoning_content, str) and reasoning_content:
                additional_kwargs["reasoning_content"] = reasoning_content
            messages.append(
                AIMessage(content=text_content, additional_kwargs=additional_kwargs)
            )

    return messages


def extract_text_content(content: ContentItem) -> str:
    """从内容中提取纯文本

    处理三种格式：
    - 普通字符串 → 直接返回
    - __agent_history JSON 字符串 → 提取 content 字段
    - 多媒体内容列表 → 提取 text 类型项
    """
    if isinstance(content, str):
        if content.startswith('{"__agent_history"'):
            try:
                data = json.loads(content)
                if isinstance(data, dict) and data.get("__agent_history"):
                    return str(data.get("content", ""))
            except (json.JSONDecodeError, TypeError):
                pass
        return content

    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                raw_text = item.get("text", "")
                text_parts.append(str(raw_text) if raw_text is not None else "")
            elif not isinstance(item, dict):
                text_parts.append(str(item))
        return " ".join(text_parts).strip() or str(content)

    return str(content)


def extract_answer_text(response: object) -> str:
    """从 LLM 响应提取用户可见的答案文本。

    兼容三种响应形态：
    - 普通 ``str`` content
    - Anthropic 风格块列表（``[{"type": "text", "text": "..."}]``）
    - reasoning 模型（DeepSeek-R1、Qwen-QwQ、OpenAI o-series 等）返回
      ``content=None``、答案存于 ``additional_kwargs["reasoning_content"]``

    提取前剥离内联 think/reasoning 标签块（Qwen3 等本地模型会把思考
    过程直接写在 content 里），避免思考文本污染脚本/结果。空文本块列表
    不会泄漏 repr（此时回退到 reasoning_content）。
    """
    raw_content = getattr(response, "content", None)
    kwargs = getattr(response, "additional_kwargs", None)
    reasoning = kwargs.get("reasoning_content") if isinstance(kwargs, dict) else None
    return _extract_answer_core(raw_content, reasoning)


def _extract_answer_core(content: object, reasoning: object) -> str:
    """共享的答案提取核心：空回退 + think 剥离 + reasoning 回退。

    ``extract_answer_text`` 与 ``extract_litellm_answer_text`` 的字段路径不同，
    但提取语义一致：content 为空/纯 think 时回退 reasoning；文本块列表不
    泄漏 repr；返回前统一 strip。
    """
    if content is None or (isinstance(content, list) and not content):
        text = ""
    else:
        text = extract_text_content(cast("ContentItem", content))
        if isinstance(content, list) and text == str(content):
            # extract_text_content 在无文本块时回退到列表 repr，
            # 这里清空以触发 reasoning_content 回退。
            text = ""
    if text:
        clean_text, _ = extract_and_strip_think_blocks(text)
        if clean_text:
            return clean_text
    return reasoning.strip() if isinstance(reasoning, str) and reasoning else ""


def extract_litellm_answer_text(response: object) -> str:
    """从 litellm.acompletion 原生响应提取用户可见文本。

    处理形态：
    - ``response.choices[0].message.content`` 为 str
    - Anthropic 风格块列表（``[{"type": "text", "text": "..."}]``）
    - reasoning 模型（DeepSeek-R1/Qwen3 等）content 为空、
      答案存于 ``message.reasoning_content``
    与 ``extract_answer_text`` 同源：内联 think 标签块剥离 + 空文本块
    列表不泄漏 repr（此时回退到 reasoning_content）。
    """
    if response is None:
        return ""
    choices = getattr(response, "choices", None)
    if not isinstance(choices, list) or not choices:
        return ""
    message = getattr(choices[0], "message", None)
    if message is None:
        return ""
    return _extract_answer_core(
        getattr(message, "content", None),
        getattr(message, "reasoning_content", None),
    )


# =============================================================================
# LLM JSON parsing
# =============================================================================

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _escape_control_chars_in_strings(text: str) -> str:
    """Escape unescaped control characters inside JSON string literals.

    JSON forbids raw control characters (code points < 0x20) inside string
    literals. Reasoning providers occasionally emit bare newlines or tabs,
    so they are rewritten to the standard short escapes (``\\n``/``\\t``)
    and any other control character to ``\\uXXXX``.
    """
    out: list[str] = []
    in_string = False
    escape_next = False
    for ch in text:
        if in_string:
            if escape_next:
                out.append(ch)
                escape_next = False
                continue
            if ch == "\\":
                out.append(ch)
                escape_next = True
                continue
            if ch == '"':
                out.append(ch)
                in_string = False
                continue
            if ch == "\n":
                out.append("\\n")
                continue
            if ch == "\t":
                out.append("\\t")
                continue
            if ch == "\r":
                out.append("\\r")
                continue
            if ord(ch) < 0x20:
                out.append(f"\\u{ord(ch):04x}")
                continue
            out.append(ch)
            continue
        if ch == '"':
            in_string = True
        out.append(ch)
    return "".join(out)


def _strip_trailing_commas(text: str) -> str:
    """Remove trailing commas inside JSON containers.

    LLMs occasionally serialize nested structures with trailing commas,
    e.g. ``[1, 2,]`` or ``{"a": 1,}``. A comma directly before ``}`` or
    ``]`` outside a string literal is never valid JSON, so dropping it is
    always safe. Repeated passes handle runs like ``{"a": 1,,}``.
    """
    previous: str | None = None
    while text != previous:
        previous = text
        out: list[str] = []
        in_string = False
        escape_next = False
        for ch in text:
            if in_string:
                out.append(ch)
                if escape_next:
                    escape_next = False
                elif ch == "\\":
                    escape_next = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
                out.append(ch)
                continue
            if ch in " \t\r\n":
                out.append(ch)
                continue
            if ch in "}]":
                i = len(out) - 1
                while i >= 0 and out[i] in " \t\r\n":
                    i -= 1
                if i >= 0 and out[i] == ",":
                    del out[i:]
            out.append(ch)
        text = "".join(out)
    return text


def _iter_json_blocks(text: str, open_ch: str, close_ch: str) -> Iterable[str]:
    """Yield every balanced ``{open_ch}...{close_ch}`` block in ``text``.

    A single state-machine pass that respects string literals, escape
    sequences, and nesting, and ignores orphan closing tokens outside any
    block. This lets callers inspect *all* candidate blocks instead of
    committing to the first opener (which reasoning providers occasionally
    precede with a format example before the real result).
    """
    depth = 0
    start = -1
    in_string = False
    escape_next = False
    for i, ch in enumerate(text):
        if in_string:
            if escape_next:
                escape_next = False
                continue
            if ch == "\\":
                escape_next = True
                continue
            if ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == open_ch:
            if depth == 0:
                start = i
            depth += 1
        elif ch == close_ch and depth > 0:
            depth -= 1
            if depth == 0 and start != -1:
                yield text[start : i + 1]
                start = -1


def _iter_json_objects(text: str) -> Iterable[str]:
    """Yield every balanced ``{...}`` object in ``text``."""
    yield from _iter_json_blocks(text, "{", "}")


def _iter_json_arrays(text: str) -> Iterable[str]:
    """Yield every balanced ``[...]`` array in ``text``."""
    yield from _iter_json_blocks(text, "[", "]")


def _iter_json_candidates(content: str) -> Iterable[str]:
    """Yield candidate JSON texts: every fence body, every balanced object,
    every balanced array, and finally the stripped raw text."""
    stripped = content.strip()
    if not stripped:
        return
    for match in _JSON_FENCE_RE.finditer(stripped):
        body = match.group(1).strip()
        if body:
            yield body
    yield from _iter_json_objects(stripped)
    yield from _iter_json_arrays(stripped)
    yield stripped


def _try_load(text: str) -> object | None:
    """Return ``json.loads(text)`` or ``None`` when the text is malformed."""
    try:
        return cast(object | None, json.loads(text))
    except json.JSONDecodeError:
        return None


def _iter_parsed_containers(
    content: str,
) -> Iterable[dict[str, object] | list[object]]:
    """Yield every dict or list recoverable from ``content``.

    Each candidate (fence body, balanced object/array, stripped raw text)
    is tried raw first and then, only on failure, with two structural
    repairs: unescaped control characters inside string literals escaped
    (bare newlines/tabs) and trailing commas removed — matching the
    artifacts reasoning providers emit.
    """
    for candidate in _iter_json_candidates(content):
        parsed = _try_load(candidate)
        if parsed is None:
            escaped = _escape_control_chars_in_strings(candidate)
            parsed = _try_load(escaped)
            if parsed is None:
                parsed = _try_load(_strip_trailing_commas(escaped))
        if isinstance(parsed, (dict, list)):
            yield parsed


def parse_llm_json_object(
    content: str,
    *,
    require_key: str | None = None,
) -> dict[str, object] | None:
    """Parse a JSON object out of an LLM reply.

    Tolerates the artifacts reasoning providers actually emit: markdown
    fences, prose framing around the object, unescaped control characters
    inside string literals (e.g. bare newlines or tabs), and multiple
    objects/fences where the last one is the real result (format examples
    preceding the actual result). When several objects are recoverable,
    the *last* parseable dict wins, matching how reasoning providers tend
    to end with the final verdict. Returns ``None`` when no object can be
    recovered.

    When ``require_key`` is given, only objects carrying that key are
    considered and the *last* such object wins — letting callers express
    contracts like "a verdict that must contain ``done``" without
    iterating candidates themselves.
    """
    parsed_last: dict[str, object] | None = None
    for parsed in _iter_parsed_containers(content):
        if isinstance(parsed, dict) and (require_key is None or require_key in parsed):
            parsed_last = parsed
    return parsed_last


def parse_llm_json_list(content: str) -> list[object] | None:
    """Parse a JSON array out of an LLM reply.

    Mirrors :func:`parse_llm_json_object` for arrays: tolerates fences,
    prose framing, unescaped control characters inside string literals,
    and multiple arrays where the last one is the real result. Returns
    ``None`` when no array can be recovered.
    """
    parsed_last: list[object] | None = None
    for parsed in _iter_parsed_containers(content):
        if isinstance(parsed, list):
            parsed_last = parsed
    return parsed_last
