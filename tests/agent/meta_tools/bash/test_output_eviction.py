"""Tests for _output_eviction truncation hints."""

from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.agent.meta_tools.bash._output_eviction import maybe_evict_large_output


@pytest.fixture
def _mock_should_filter():
    """Force should_filter to return True for any input."""
    with patch(
        "myrm_agent_harness.agent.meta_tools.bash._output_eviction.should_filter",
        return_value=True,
    ):
        yield


@pytest.fixture
def _mock_detect_non_structural():
    """Detect content type as plain text (non-structural) to hit _create_smart_preview."""
    with patch(
        "myrm_agent_harness.agent.meta_tools.bash._output_eviction.detect_content_type",
        return_value="text",
    ):
        yield


@pytest.fixture
def mock_executor():
    executor = AsyncMock()
    executor.write_file = AsyncMock()
    executor.mkdir = AsyncMock()
    return executor


@pytest.mark.asyncio
@pytest.mark.usefixtures("_mock_should_filter", "_mock_detect_non_structural")
async def test_eviction_hint_references_file_read_tool(mock_executor):
    """Main branch: hint must reference file_read_tool, not cat."""
    with patch(
        "myrm_agent_harness.agent.meta_tools.bash._output_eviction._save_to_file",
        return_value="output.txt",
    ):
        result = await maybe_evict_large_output("x" * 50000, mock_executor)

    assert "file_read_tool" in result
    assert "cat " not in result
    assert "offset/limit" not in result
    assert ":100-200" in result


@pytest.mark.asyncio
@pytest.mark.usefixtures("_mock_should_filter")
async def test_eviction_fallback_hint_references_file_read_tool(mock_executor):
    """Fallback branch (structural filter fails): hint must reference file_read_tool."""
    with (
        patch(
            "myrm_agent_harness.agent.meta_tools.bash._output_eviction._save_to_file",
            return_value="output.txt",
        ),
        patch(
            "myrm_agent_harness.agent.meta_tools.bash._output_eviction.detect_content_type",
            side_effect=RuntimeError("simulated filter failure"),
        ),
    ):
        result = await maybe_evict_large_output("x" * 50000, mock_executor)

    assert "file_read_tool" in result
    assert "cat " not in result
    assert ":100-200" in result


@pytest.mark.asyncio
@pytest.mark.usefixtures("_mock_should_filter", "_mock_detect_non_structural")
async def test_eviction_no_executor_no_file_hint():
    """Without executor, no file_path hint should appear."""
    result = await maybe_evict_large_output("x" * 50000)
    assert "Full output saved to" not in result
    assert "LARGE OUTPUT TRUNCATED" in result


@pytest.mark.asyncio
@pytest.mark.usefixtures("_mock_should_filter", "_mock_detect_non_structural")
async def test_eviction_file_save_failure_still_has_preview(mock_executor):
    """If file save fails, preview should still be returned without file hint."""
    with patch(
        "myrm_agent_harness.agent.meta_tools.bash._output_eviction._save_to_file",
        side_effect=OSError("disk full"),
    ):
        result = await maybe_evict_large_output("x" * 50000, mock_executor)
    assert "LARGE OUTPUT TRUNCATED" in result
    assert "Full output saved to" not in result


@pytest.mark.asyncio
@pytest.mark.usefixtures("_mock_should_filter")
async def test_eviction_hint_includes_actual_file_path(mock_executor):
    """Hint must include the actual file path in the line range example."""
    with (
        patch(
            "myrm_agent_harness.agent.meta_tools.bash._output_eviction._save_to_file",
            return_value=".context/session123/evicted/output_abc.txt",
        ),
        patch(
            "myrm_agent_harness.agent.meta_tools.bash._output_eviction.detect_content_type",
            return_value="text",
        ),
    ):
        result = await maybe_evict_large_output("x" * 50000, mock_executor)
    assert ".context/session123/evicted/output_abc.txt:100-200" in result


@pytest.mark.asyncio
async def test_eviction_skips_small_output():
    """Small output should pass through unchanged."""
    result = await maybe_evict_large_output("small output")
    assert result == "small output"
