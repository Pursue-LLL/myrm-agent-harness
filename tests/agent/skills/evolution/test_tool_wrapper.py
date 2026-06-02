from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.skills.evolution.execution.tool_wrapper import ToolWrapper


class MockTool(BaseTool):
    name: str = "mock_tool"
    description: str = "test tool"

    async def _arun(self, *args, **kwargs):
        return "success"

    def _run(self, *args, **kwargs):
        return "success"

@pytest.fixture
def mock_executor():
    # Since ExecutorContextManager uses the executor but we don't deeply inspect it here,
    # just providing a mock is fine. Wait, ExecutorContextManager is an async context manager
    # but the implementation sets it via contextvars. We just need an AsyncMock if it's async context.
    executor = MagicMock()
    return executor

@pytest.mark.asyncio
async def test_tool_wrapper_success(mock_executor):
    base_tool = MockTool()
    with patch.object(MockTool, "ainvoke", new_callable=AsyncMock) as mock_invoke:
        mock_invoke.return_value = "tool_result"
        wrapper = ToolWrapper(base_tool, mock_executor)
        assert wrapper.name == "mock_tool"

        result = await wrapper.ainvoke({"path": "test.py"})
        assert result == "tool_result"
        mock_invoke.assert_called_once_with({"path": "test.py"}, None)

@pytest.mark.asyncio
async def test_tool_wrapper_disable_smart_error(mock_executor):
    base_tool = MockTool()
    with patch.object(MockTool, "ainvoke", new_callable=AsyncMock) as mock_invoke:
        mock_invoke.side_effect = FileNotFoundError("missing")
        wrapper = ToolWrapper(base_tool, mock_executor, enable_smart_error=False)
        with pytest.raises(FileNotFoundError):
            await wrapper.ainvoke({"path": "test.py"})

@pytest.mark.asyncio
async def test_tool_wrapper_file_not_found_url(mock_executor):
    base_tool = MockTool()
    with patch.object(MockTool, "ainvoke", new_callable=AsyncMock) as mock_invoke:
        mock_invoke.side_effect = FileNotFoundError("missing")
        wrapper = ToolWrapper(base_tool, mock_executor, enable_smart_error=True)
        result = await wrapper.ainvoke({"path": "http://example.com"})
        assert "Cannot read URL: http://example.com" in result

@pytest.mark.asyncio
async def test_tool_wrapper_file_not_found_similar(mock_executor):
    base_tool = MockTool()
    with patch.object(MockTool, "ainvoke", new_callable=AsyncMock) as mock_invoke:
        mock_invoke.side_effect = FileNotFoundError("missing")
        wrapper = ToolWrapper(base_tool, mock_executor, enable_smart_error=True)
        wrapper._find_similar_paths = AsyncMock(return_value=["test2.py", "test3.py"])

        result = await wrapper.ainvoke({"path": "test.py"})
        assert "Did you mean: test2.py?" in result
        assert "Or: test3.py" in result

@pytest.mark.asyncio
async def test_tool_wrapper_file_not_found_parent(mock_executor):
    base_tool = MockTool()
    with patch.object(MockTool, "ainvoke", new_callable=AsyncMock) as mock_invoke:
        mock_invoke.side_effect = FileNotFoundError("missing")
        wrapper = ToolWrapper(base_tool, mock_executor, enable_smart_error=True)
        wrapper._find_similar_paths = AsyncMock(return_value=[])
        wrapper._path_exists = AsyncMock(return_value=True)
        wrapper._list_dir = AsyncMock(return_value=["other.py"])

        result = await wrapper.ainvoke({"path": "test.py"})
        assert "Available files in" in result
        assert "other.py" in result

@pytest.mark.asyncio
async def test_tool_wrapper_permission_error(mock_executor):
    base_tool = MockTool()
    with patch.object(MockTool, "ainvoke", new_callable=AsyncMock) as mock_invoke:
        mock_invoke.side_effect = PermissionError("denied")
        wrapper = ToolWrapper(base_tool, mock_executor, enable_smart_error=True)
        result = await wrapper.ainvoke({"path": "/root/test.py"})
        assert "Permission denied: /root/test.py" in result

@pytest.mark.asyncio
async def test_tool_wrapper_generic_error(mock_executor):
    base_tool = MockTool()
    with patch.object(MockTool, "ainvoke", new_callable=AsyncMock) as mock_invoke:
        mock_invoke.side_effect = ValueError("bad value")
        wrapper = ToolWrapper(base_tool, mock_executor, enable_smart_error=True)
        result = await wrapper.ainvoke({"path": "test.py"})
        assert "Error in mock_tool: bad value" in result

@pytest.mark.asyncio
async def test_find_similar_paths(mock_executor):
    base_tool = MockTool()
    wrapper = ToolWrapper(base_tool, mock_executor)

    wrapper._path_exists = AsyncMock(return_value=True)
    wrapper._list_dir = AsyncMock(return_value=["test_abc.py", "other.txt", "abc_test.py"])

    similar = await wrapper._find_similar_paths("test.py")
    assert "test_abc.py" in similar or "./test_abc.py" in similar or "abc_test.py" in similar or "./abc_test.py" in similar
    assert "other.txt" not in similar

    wrapper._path_exists = AsyncMock(return_value=False)
    similar2 = await wrapper._find_similar_paths("test.py")
    assert similar2 == []
