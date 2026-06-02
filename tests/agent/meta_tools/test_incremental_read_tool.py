"""Tests for the read_incremental_log_tool."""

from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.incremental_read_tool import create_incremental_read_tool
from myrm_agent_harness.utils.errors import ToolError


@pytest.fixture
def mock_executor(tmp_path):
    executor = MagicMock()
    executor.get_workspace_path.return_value = tmp_path
    return executor


@pytest.mark.asyncio
async def test_incremental_read_basic(tmp_path):
    # Setup test file
    log_file = tmp_path / "test.log"
    log_file.write_text("line 1\nline 2\n")

    with patch("myrm_agent_harness.agent.meta_tools.file_ops.incremental_read_tool.get_executor") as mock_get_exec:
        executor = MagicMock()
        executor.get_workspace_path.return_value = tmp_path
        mock_get_exec.return_value = executor

        tool = create_incremental_read_tool()

        # First read
        result1 = await tool.ainvoke({"file_path": "test.log", "cursor": "0"})
        assert "line 1" in result1
        assert "line 2" in result1

        # Extract next_offset from result1 string manually for testing
        # Format is: [System] Current log read complete. To read new logs next time, use cursor=14:1234:ab12.
        offset_idx = result1.rfind("cursor=")
        assert offset_idx != -1
        next_cursor = result1[offset_idx + len("cursor="):].strip(".")

        # Second read with NO new data
        result2 = await tool.ainvoke({"file_path": "test.log", "cursor": next_cursor})
        assert "[No new logs found]" in result2

        # Append data
        with open(log_file, "a") as f:
            f.write("line 3\nline 4\n")

        # Third read WITH new data
        result3 = await tool.ainvoke({"file_path": "test.log", "cursor": next_cursor})
        assert "line 1" not in result3
        assert "line 3" in result3
        assert "line 4" in result3


@pytest.mark.asyncio
async def test_incremental_read_with_filter(tmp_path):
    log_file = tmp_path / "test.log"
    log_file.write_text("info: start\nerror: failed to load\nwarn: slow\ninfo: end\n")

    with patch("myrm_agent_harness.agent.meta_tools.file_ops.incremental_read_tool.get_executor") as mock_get_exec:
        executor = MagicMock()
        executor.get_workspace_path.return_value = tmp_path
        mock_get_exec.return_value = executor

        tool = create_incremental_read_tool()

        # Read with filter, context_lines=0
        result = await tool.ainvoke({
            "file_path": "test.log",
            "cursor": "0",
            "filter_pattern": "(?i)error|warn",
            "context_lines": 0
        })
        assert "error: failed to load" in result
        assert "warn: slow" in result
        assert "info: start" not in result
        assert "info: end" not in result


@pytest.mark.asyncio
async def test_incremental_read_with_context(tmp_path):
    log_file = tmp_path / "test.log"
    log_file.write_text("line 1\nline 2\nException here\nline 4\nline 5\n")

    with patch("myrm_agent_harness.agent.meta_tools.file_ops.incremental_read_tool.get_executor") as mock_get_exec:
        executor = MagicMock()
        executor.get_workspace_path.return_value = tmp_path
        mock_get_exec.return_value = executor

        tool = create_incremental_read_tool()

        # Read with filter and context_lines=1
        result = await tool.ainvoke({
            "file_path": "test.log",
            "cursor": "0",
            "filter_pattern": "Exception",
            "context_lines": 1
        })
        assert "line 2" in result
        assert "Exception here" in result
        assert "line 4" in result
        assert "line 1" not in result
        assert "line 5" not in result


@pytest.mark.asyncio
async def test_incremental_read_ansi_strip(tmp_path):
    log_file = tmp_path / "test.log"
    log_file.write_text("\x1b[31mError:\x1b[0m Failed\n")

    with patch("myrm_agent_harness.agent.meta_tools.file_ops.incremental_read_tool.get_executor") as mock_get_exec:
        executor = MagicMock()
        executor.get_workspace_path.return_value = tmp_path
        mock_get_exec.return_value = executor

        tool = create_incremental_read_tool()

        result = await tool.ainvoke({
            "file_path": "test.log",
            "cursor": "0",
        })
        # The result should have stripped the ANSI codes
        assert "Error: Failed" in result
        assert "\x1b[31m" not in result


@pytest.mark.asyncio
async def test_incremental_read_file_rotation(tmp_path):
    log_file = tmp_path / "test.log"
    log_file.write_text("A" * 100) # 100 bytes

    with patch("myrm_agent_harness.agent.meta_tools.file_ops.incremental_read_tool.get_executor") as mock_get_exec:
        executor = MagicMock()
        executor.get_workspace_path.return_value = tmp_path
        mock_get_exec.return_value = executor

        tool = create_incremental_read_tool()

        # Start reading at offset 100, but file is overwritten to be smaller
        log_file.write_text("new data\n") # ~9 bytes

        # The tool should automatically reset offset to 0
        result = await tool.ainvoke({"file_path": "test.log", "cursor": "100"})
        assert "new data" in result


@pytest.mark.asyncio
async def test_incremental_read_path_traversal(tmp_path):
    with patch("myrm_agent_harness.agent.meta_tools.file_ops.incremental_read_tool.get_executor") as mock_get_exec:
        executor = MagicMock()
        executor.get_workspace_path.return_value = tmp_path
        mock_get_exec.return_value = executor

        tool = create_incremental_read_tool()

        with pytest.raises(ToolError, match="Path traversal detected"):
            await tool.ainvoke({"file_path": "../../../../etc/passwd", "cursor": "0"})


@pytest.mark.asyncio
async def test_incremental_read_rotation_hash(tmp_path):
    log_file = tmp_path / "test.log"
    log_file.write_text("old_data_first_line\n" + "A" * 100 + "\n") # file is ~120 bytes

    with patch("myrm_agent_harness.agent.meta_tools.file_ops.incremental_read_tool.get_executor") as mock_get_exec:
        executor = MagicMock()
        executor.get_workspace_path.return_value = tmp_path
        mock_get_exec.return_value = executor

        tool = create_incremental_read_tool()

        # First read to get the cursor
        result1 = await tool.ainvoke({"file_path": "test.log", "cursor": "0"})
        offset_idx = result1.rfind("cursor=")
        next_cursor = result1[offset_idx + len("cursor="):].strip(".")

        # Now simulate copytruncate (size doesn't shrink, inode might not change, but content hash changes)
        log_file.write_text("new_data_first_line\n" + "B" * 150 + "\n") # larger size, different hash

        # Read again with the old cursor
        result2 = await tool.ainvoke({"file_path": "test.log", "cursor": next_cursor})

        # It should detect rotation via hash and read from 0
        assert "new_data_first_line" in result2
        assert "old_data_first_line" not in result2


@pytest.mark.asyncio
async def test_incremental_read_rotation_inode(tmp_path):
    log_file = tmp_path / "test.log"
    log_file.write_text("old_data_first_line\n" + "A" * 100 + "\n") # file is ~120 bytes

    with patch("myrm_agent_harness.agent.meta_tools.file_ops.incremental_read_tool.get_executor") as mock_get_exec:
        executor = MagicMock()
        executor.get_workspace_path.return_value = tmp_path
        mock_get_exec.return_value = executor

        tool = create_incremental_read_tool()

        # First read to get the cursor
        result1 = await tool.ainvoke({"file_path": "test.log", "cursor": "0"})
        offset_idx = result1.rfind("cursor=")
        next_cursor = result1[offset_idx + len("cursor="):].strip(".")

        # Now simulate mv rotation (inode changes)
        log_file.unlink()
        log_file.write_text("old_data_first_line\n" + "B" * 150 + "\n") # Same first line, but new inode!

        # Read again with the old cursor
        result2 = await tool.ainvoke({"file_path": "test.log", "cursor": next_cursor})

        # It should detect rotation via inode and read from 0, even though hash matches!
        assert "old_data_first_line" in result2
        assert "BBBB" in result2
