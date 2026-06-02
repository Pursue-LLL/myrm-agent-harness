"""Unit tests for optional compress-time offload callback with selective thresholding."""

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from myrm_agent_harness.agent.context_management.infra.schemas import ContextConfig
from myrm_agent_harness.agent.context_management.strategies.compactor import (
    OFFLOAD_THRESHOLD_TOKENS,
    compress_messages_async,
    compress_tool_message_async,
)


def _generate_large_varied_content(min_tokens: int) -> str:
    """生成多样化的大文本内容,确保 token 数达到阈值

    重复字符会被 tokenizer 高度压缩,需要多样化内容。
    """
    import string

    words = [
        "hello",
        "world",
        "test",
        "data",
        "content",
        "information",
        "system",
        "process",
        "function",
        "variable",
        "method",
        "class",
        "object",
        "instance",
        "parameter",
        "return",
        "value",
        "result",
        "output",
        "input",
        "query",
        "response",
        "request",
    ]

    lines = []
    for i in range(min_tokens // 3):  # 每行约 3 tokens
        word = words[i % len(words)]
        lines.append(f"{word}_{i}: {string.ascii_letters[i % 52]} {i * 2}")

    return "\n".join(lines)


@pytest.mark.asyncio
async def test_compress_tool_message_async_with_offload_large_output() -> None:
    """测试大输出(>=阈值)触发落盘,compressed content 包含 FILE 和 RECOVER 行"""
    written: list[tuple[str, str]] = []

    async def offload(*, content: str, tool_name: str, scope_id: str | None) -> str:
        written.append((tool_name, content))
        return f".context/{scope_id or 'global'}/compacted_{tool_name}.txt"

    # 构造大于阈值的输出(使用多样化内容确保 token 数足够)
    large_content = _generate_large_varied_content(OFFLOAD_THRESHOLD_TOKENS + 1000)
    tool = ToolMessage(content=large_content, tool_call_id="tc1", name="web_fetch_tool")
    ai = AIMessage(
        content="", tool_calls=[{"id": "tc1", "name": "web_fetch_tool", "args": {"url": "https://example.com"}}]
    )

    saved = await compress_tool_message_async(tool, ai, on_offload=offload, chat_id="session123", user_id="u1")
    assert saved > 0
    assert len(written) == 1
    assert written[0][0] == "web_fetch_tool"
    body = str(tool.content)
    assert "FILE: /persistent/.context/session123/compacted_web_fetch_tool.txt" in body
    assert "RECOVER: cat /persistent/.context/session123/compacted_web_fetch_tool.txt" in body
    assert "COMPACTED: web_fetch_tool" in body


@pytest.mark.asyncio
async def test_compress_tool_message_async_small_output_skip_offload() -> None:
    """测试小输出(<阈值)跳过落盘,不包含 FILE/RECOVER 行"""
    offload_called = False

    async def offload(*, content: str, tool_name: str, scope_id: str | None) -> str:
        nonlocal offload_called
        _ = content, tool_name, scope_id
        offload_called = True
        return ".context/should_not_be_called.txt"

    # 构造小于阈值的输出
    small_content = "x" * 100
    tool = ToolMessage(content=small_content, tool_call_id="tc2", name="bash_code_execute_tool")
    ai = AIMessage(
        content="", tool_calls=[{"id": "tc2", "name": "bash_code_execute_tool", "args": {"command": "echo hi"}}]
    )

    await compress_tool_message_async(tool, ai, on_offload=offload, chat_id="session123", user_id=None)
    # 关键验证:offload 未被调用(小输出跳过落盘)
    assert not offload_called
    body = str(tool.content)
    assert "FILE:" not in body
    assert "RECOVER:" not in body
    assert "COMPACTED:" in body


@pytest.mark.asyncio
async def test_compress_tool_message_async_offload_failure_degrades_gracefully() -> None:
    """测试回调失败时,压缩照常进行,但不包含 FILE/RECOVER 行"""

    async def offload(*, content: str, tool_name: str, scope_id: str | None) -> str:
        _ = content, tool_name, scope_id
        raise RuntimeError("disk full")

    large_content = _generate_large_varied_content(OFFLOAD_THRESHOLD_TOKENS + 1000)
    tool = ToolMessage(content=large_content, tool_call_id="tc3", name="bash_code_execute_tool")
    ai = AIMessage(
        content="",
        tool_calls=[
            {"id": "tc3", "name": "bash_code_execute_tool", "args": {"command": "echo hi"}},
        ],
    )

    saved = await compress_tool_message_async(tool, ai, on_offload=offload, chat_id=None, user_id=None)
    assert saved >= 0
    body = str(tool.content)
    assert "FILE:" not in body
    assert "RECOVER:" not in body
    assert body.startswith("COMPACTED:")


@pytest.mark.asyncio
async def test_skill_select_tool_compression_preserves_recovery_info() -> None:
    """Verify skill_select_tool results are compressed reversibly with RECOVER instructions.

    This proves we don't need DeerFlow-style 'skill bundle rescue' because:
    1. Compressed output retains the skill identifier (file path)
    2. Large outputs get offloaded with FILE/RECOVER instructions
    3. Model can cat the file to restore full skill content
    """
    offload_called = False

    async def offload(*, content: str, tool_name: str, scope_id: str | None) -> str:
        nonlocal offload_called
        _ = content, tool_name
        offload_called = True
        return f".context/{scope_id}/skills/skill_content.txt"

    skill_content = _generate_large_varied_content(OFFLOAD_THRESHOLD_TOKENS + 1000)
    tool = ToolMessage(
        content=skill_content,
        tool_call_id="skill_tc1",
        name="skill_select_tool",
    )
    ai = AIMessage(
        content="",
        tool_calls=[{"id": "skill_tc1", "name": "skill_select_tool", "args": {"path": "/skills/coding.md"}}],
    )

    saved = await compress_tool_message_async(tool, ai, on_offload=offload, chat_id="chat_skill", user_id="u1")
    assert saved > 0
    assert offload_called

    body = str(tool.content)
    assert "COMPACTED:" in body
    assert "skill_select_tool" in body or "/skills/coding.md" in body
    assert "FILE:" in body
    assert "RECOVER: cat" in body
    assert ".context/chat_skill/skills/skill_content.txt" in body


@pytest.mark.asyncio
async def test_skill_select_tool_small_content_compresses_without_offload() -> None:
    """Small skill content is compressed in-place without offload, retaining identifier."""
    async def offload(*, content: str, tool_name: str, scope_id: str | None) -> str:
        _ = content, tool_name, scope_id
        raise AssertionError("Should not be called for small content")

    tool = ToolMessage(
        content="# Coding Skill\n\nThis is a short skill description.",
        tool_call_id="skill_tc2",
        name="skill_select_tool",
    )
    ai = AIMessage(
        content="",
        tool_calls=[{"id": "skill_tc2", "name": "skill_select_tool", "args": {"path": "/skills/short.md"}}],
    )

    await compress_tool_message_async(tool, ai, on_offload=offload, chat_id="chat_skill2", user_id="u1")

    body = str(tool.content)
    assert "COMPACTED:" in body
    assert "/skills/short.md" in body
    assert "FILE:" not in body


@pytest.mark.asyncio
async def test_compress_messages_async_passes_offload_to_tool_compress() -> None:
    """测试 compress_messages_async 将 on_compress_offload 传递给单个工具压缩,且选择性落盘生效"""
    offload_calls: list[str] = []

    async def offload(*, content: str, tool_name: str, scope_id: str | None) -> str:
        _ = content
        offload_calls.append(tool_name)
        return f".context/{scope_id or 'global'}/{tool_name}.txt"

    messages: list = []
    for i in range(7):
        tcid = f"id{i}"
        messages.append(
            AIMessage(
                content="", tool_calls=[{"id": tcid, "name": "web_search_tool", "args": {"questions": [f"q{i}"]}}]
            )
        )
        unique_content = _generate_large_varied_content(OFFLOAD_THRESHOLD_TOKENS + 1000)
        unique_content += f"\n--- unique marker {i} ---"
        messages.append(ToolMessage(content=unique_content, tool_call_id=tcid, name="web_search_tool"))

    cfg = ContextConfig(max_context_tokens=128000, compress_min_save=0, keep_recent_calls=2)
    _, saved = await compress_messages_async(
        messages, dynamic_min_save=0, config=cfg, on_compress_offload=offload, chat_id="chat123", user_id="user1"
    )
    assert saved > 0
    # 应该有 5 个工具调用被压缩,且都触发了落盘
    assert len(offload_calls) == 5
    assert all(name == "web_search_tool" for name in offload_calls)
