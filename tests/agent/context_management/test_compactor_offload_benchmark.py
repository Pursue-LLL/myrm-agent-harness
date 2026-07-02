"""Benchmark tests to measure actual offload performance impact."""

import time

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from myrm_agent_harness.agent.context_management.infra.schemas import ContextConfig
from myrm_agent_harness.agent.context_management.strategies.compactor import (
    OFFLOAD_THRESHOLD_TOKENS,
    compress_messages_async,
)


def _generate_large_varied_content(min_tokens: int) -> str:
    """生成多样化的大文本内容"""
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
    for i in range(min_tokens // 3):
        word = words[i % len(words)]
        lines.append(f"{word}_{i}: {string.ascii_letters[i % 52]} {i * 2}")

    return "\n".join(lines)


@pytest.mark.asyncio
async def test_benchmark_small_outputs_no_io() -> None:
    """基准测试:小输出(<5k tokens)不触发 I/O,纯内存压缩"""
    io_call_count = 0

    async def mock_offload(*, content: str, tool_name: str, scope_id: str | None) -> str:
        nonlocal io_call_count
        _ = content, scope_id
        io_call_count += 1
        return f".context/{tool_name}.txt"

    # 100 个小输出的工具调用
    messages: list = []
    small_content = "small result " * 50  # ~100 tokens
    for i in range(100):
        tcid = f"id{i}"
        messages.append(
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": tcid,
                        "name": "bash_code_execute_tool",
                        "args": {"command": f"echo {i}"},
                    }
                ],
            )
        )
        messages.append(ToolMessage(content=small_content, tool_call_id=tcid, name="bash_code_execute_tool"))

    cfg = ContextConfig(max_context_tokens=128000, compress_min_save=0, keep_recent_calls=5)

    start = time.perf_counter()
    _, saved = await compress_messages_async(
        messages, dynamic_min_save=0, config=cfg, on_compress_offload=mock_offload, chat_id="bench", user_id="user"
    )
    elapsed_ms = (time.perf_counter() - start) * 1000

    # 关键断言:小输出不应触发任何 I/O
    assert io_call_count == 0, f"Expected 0 I/O calls for small outputs, got {io_call_count}"
    assert saved > 0
    print(f"\n[Benchmark] 100 small outputs: {elapsed_ms:.1f}ms, 0 I/O calls")


@pytest.mark.asyncio
async def test_benchmark_large_outputs_with_io() -> None:
    """基准测试:大输出(>=5k tokens)触发 I/O 落盘"""
    io_call_count = 0
    total_io_time_ms = 0.0

    async def mock_offload(*, content: str, tool_name: str, scope_id: str | None) -> str:
        nonlocal io_call_count, total_io_time_ms
        _ = content
        io_call_count += 1
        # 模拟文件写入耗时(Local: ~1-5ms, E2B: ~10-50ms)
        start = time.perf_counter()
        await __import__("asyncio").sleep(0.002)  # 模拟 2ms I/O
        total_io_time_ms += (time.perf_counter() - start) * 1000
        return f".context/{scope_id}/{tool_name}_{io_call_count}.txt"

    # 10 个大输出的工具调用(keep_recent=2 -> 压缩 8 个)
    messages: list = []
    for i in range(10):
        tcid = f"id{i}"
        messages.append(
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": tcid,
                        "name": "web_search_tool",
                        "args": {"query": f"test{i}"},
                    }
                ],
            )
        )
        unique_content = _generate_large_varied_content(OFFLOAD_THRESHOLD_TOKENS + 1000)
        unique_content += f"\n--- unique benchmark marker {i} ---"
        messages.append(ToolMessage(content=unique_content, tool_call_id=tcid, name="web_search_tool"))

    cfg = ContextConfig(max_context_tokens=128000, compress_min_save=0, keep_recent_calls=2)

    start = time.perf_counter()
    _, saved = await compress_messages_async(
        messages, dynamic_min_save=0, config=cfg, on_compress_offload=mock_offload, chat_id="bench", user_id="user"
    )
    elapsed_ms = (time.perf_counter() - start) * 1000

    # 应压缩 10-2=8 个,全部触发 I/O
    assert io_call_count == 8, f"Expected 8 I/O calls, got {io_call_count}"
    assert saved > 0
    print(
        f"\n[Benchmark] 10 large outputs: {elapsed_ms:.1f}ms total, {io_call_count} I/O calls, {total_io_time_ms:.1f}ms I/O time"
    )


@pytest.mark.asyncio
async def test_benchmark_mixed_outputs() -> None:
    """基准测试:混合场景(90 个小 + 10 个大)验证选择性落盘"""
    io_call_count = 0

    async def mock_offload(*, content: str, tool_name: str, scope_id: str | None) -> str:
        nonlocal io_call_count
        _ = content, scope_id
        io_call_count += 1
        await __import__("asyncio").sleep(0.002)
        return f".context/{tool_name}.txt"

    messages: list = []
    small_content = "x" * 100

    # 90 个小输出
    for i in range(90):
        tcid = f"small_{i}"
        messages.append(AIMessage(content="", tool_calls=[{"id": tcid, "name": "bash_code_execute_tool", "args": {}}]))
        messages.append(ToolMessage(content=small_content, tool_call_id=tcid, name="bash_code_execute_tool"))

    # 10 个大输出
    for i in range(10):
        tcid = f"large_{i}"
        messages.append(AIMessage(content="", tool_calls=[{"id": tcid, "name": "search_tool", "args": {}}]))
        unique_large = _generate_large_varied_content(OFFLOAD_THRESHOLD_TOKENS + 1000)
        unique_large += f"\n--- unique mixed marker {i} ---"
        messages.append(ToolMessage(content=unique_large, tool_call_id=tcid, name="search_tool"))

    cfg = ContextConfig(max_context_tokens=128000, compress_min_save=0, keep_recent_calls=5)

    start = time.perf_counter()
    _, saved = await compress_messages_async(
        messages, dynamic_min_save=0, config=cfg, on_compress_offload=mock_offload, chat_id="bench", user_id="user"
    )
    elapsed_ms = (time.perf_counter() - start) * 1000

    # 验证选择性落盘:总共 100 个调用(90 小 + 10 大),保留最近 5 个,压缩最旧 95 个
    # 最旧 95 个 = 前 90 个小 + 前 5 个大
    # 只有前 5 个大会触发 I/O(小输出跳过落盘)
    print(
        f"\n[Benchmark] Mixed (90 small + 10 large): {elapsed_ms:.1f}ms, {io_call_count} I/O calls (only large outputs)"
    )
    assert io_call_count <= 10, f"Expected ≤10 I/O calls (only large), got {io_call_count}"
    assert saved > 0
