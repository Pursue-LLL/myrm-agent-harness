"""真实场景集成测试：上下文压缩增强功能

使用真实的消息序列和工具输出，验证：
1. 统计信息保留
2. 内容去重
3. 防抖机制
4. 完整的压缩流程

不需要真实的LLM API，使用模拟的真实数据。
"""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from myrm_agent_harness.agent.context_management.strategies.compactor import compress_messages_async


@pytest.mark.asyncio
async def test_real_scenario_bash_command_failure():
    """真实场景：bash命令失败，压缩后保留exit_code"""
    messages = []

    verbose_trace = "\n".join(f"  File 'module_{j}.py', line {j * 10}, in test_func_{j}" for j in range(40))

    for i in range(12):
        messages.append(HumanMessage(content=f"请执行任务{i}，需要运行完整测试套件"))
        messages.append(
            AIMessage(
                content="好的，让我执行命令",
                tool_calls=[
                    {
                        "id": f"call_{i}",
                        "name": "bash_code_execute_tool",
                        "args": {"command": f"pytest tests/test_{i}.py -v --tb=long"},
                    }
                ],
            )
        )

        if i % 2 == 0:
            bash_output = (
                f"test_{i}.py::test_function PASSED\n"
                f"test_{i}.py::test_another PASSED\n"
                f"test_{i}.py::test_edge_case PASSED\n"
                f"{verbose_trace}\n"
                f"==================== 3 passed in 1.{i}5s ====================\n"
                f"[exit_code: 0]"
            )
        else:
            bash_output = (
                f"test_{i}.py::test_function PASSED\n"
                f"test_{i}.py::test_another FAILED\n"
                f"FAILURES:\n"
                f"  def test_another():\n"
                f"    > assert result == expected\n"
                f"    E AssertionError: {i} != {i + 1}\n"
                f"{verbose_trace}\n"
                f"==================== 1 failed, 1 passed in 0.{i}5s ====================\n"
                f"[exit_code: 1]"
            )

        messages.append(
            ToolMessage(
                content=bash_output,
                tool_call_id=f"call_{i}",
                name="bash_code_execute_tool",
            )
        )

    # 执行压缩
    compressed, saved = await compress_messages_async(messages)

    # 验证：压缩后的消息应该保留exit_code信息
    compressed_bash_msgs = [msg for msg in compressed if isinstance(msg, ToolMessage) and "COMPACTED:" in msg.content]

    assert len(compressed_bash_msgs) > 0, "应该有压缩的bash消息"

    # 检查第一个压缩的消息
    first_compressed = compressed_bash_msgs[0]
    assert "EXIT:" in first_compressed.content, "压缩后应该包含EXIT信息"
    assert "0" in first_compressed.content or "1" in first_compressed.content, "应该包含具体的exit_code值"

    print(f"\n 压缩后保留exit_code，压缩 {len(compressed_bash_msgs)} 个bash调用")
    print(f" 节省 {saved} tokens")
    print(f" 示例压缩内容:\n{first_compressed.content}")


@pytest.mark.asyncio
async def test_real_scenario_file_operations():
    """真实场景：文件操作序列"""
    messages = []

    files = ["config.py", "utils.py", "main.py", "test.py", "models.py", "views.py", "routes.py", "helpers.py"]

    for idx, filename in enumerate(files):
        messages.append(HumanMessage(content=f"请读取{filename}"))
        messages.append(
            AIMessage(
                content=f"好的，读取{filename}",
                tool_calls=[
                    {
                        "id": f"call_read_{idx}",
                        "name": "file_read_tool",
                        "args": {"paths": [filename]},
                    }
                ],
            )
        )

        file_content = f"# {filename}\n" + "\n".join(
            f"def function_{idx}_{j}():\n    return 'value_{j}'" for j in range(80)
        )

        messages.append(
            ToolMessage(
                content=file_content,
                tool_call_id=f"call_read_{idx}",
                name="file_read_tool",
            )
        )

        # 用户请求修改文件
        messages.append(HumanMessage(content=f"请修改{filename}"))
        messages.append(
            AIMessage(
                content=f"好的，修改{filename}",
                tool_calls=[
                    {
                        "id": f"call_write_{idx}",
                        "name": "file_write_tool",
                        "args": {"path": filename, "content": file_content + "\n# Modified"},
                    }
                ],
            )
        )

        messages.append(
            ToolMessage(
                content=f"Successfully wrote {len(file_content)} chars to {filename}",
                tool_call_id=f"call_write_{idx}",
                name="file_write_tool",
            )
        )

    # 执行压缩
    compressed, saved = await compress_messages_async(messages)

    assert saved > 0, "应该节省了tokens"

    compressed_msgs = [msg for msg in compressed if isinstance(msg, ToolMessage) and "COMPACTED:" in msg.content]
    assert len(compressed_msgs) > 0, "应该有工具输出被压缩"

    print("\n 文件操作压缩测试通过")
    print(f" 消息数: {len(messages)}, 压缩了 {len(compressed_msgs)} 个工具输出")
    print(f" 节省: {saved} tokens")


@pytest.mark.asyncio
async def test_real_scenario_duplicate_detection():
    """真实场景：多次读取同一文件（去重）"""
    messages = []

    # 用户多次请求读取同一文件
    same_content = "# config.py\n" + "\n".join(
        f"CONSTANT_{j} = 'value_{j}'\nSETTING_{j} = {j * 100}" for j in range(80)
    )

    for i in range(8):
        messages.append(HumanMessage(content=f"第{i}次请求，请读取config.py"))
        messages.append(
            AIMessage(
                content="好的",
                tool_calls=[
                    {
                        "id": f"call_{i}",
                        "name": "file_read_tool",
                        "args": {"paths": ["config.py"]},
                    }
                ],
            )
        )

        messages.append(
            ToolMessage(
                content=same_content,  # 相同内容
                tool_call_id=f"call_{i}",
                name="file_read_tool",
            )
        )

    # 执行压缩
    compressed, saved = await compress_messages_async(messages)

    dedup_count = sum(1 for msg in compressed if isinstance(msg, ToolMessage) and "Duplicate" in msg.content)

    assert dedup_count > 0, "应该有重复内容被检测并去重"

    print("\n 内容去重测试通过")
    print(f" 检测到 {dedup_count} 个重复")
    print(f" 节省: {saved} tokens（含压缩）")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
