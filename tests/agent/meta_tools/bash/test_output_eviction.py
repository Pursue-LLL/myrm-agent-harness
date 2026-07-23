"""Tests for _output_eviction truncation hints."""

from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.agent.meta_tools.bash._output_eviction import (
    EvictionResult,
    maybe_evict_large_output,
)


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

    assert isinstance(result, EvictionResult)
    assert "file_read_tool" in result.text
    assert "cat " not in result.text
    assert "offset=" in result.text
    assert "limit=" in result.text
    assert result.evicted_ref == "output.txt"


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

    assert isinstance(result, EvictionResult)
    assert "file_read_tool" in result.text
    assert "cat " not in result.text
    assert "offset=" in result.text
    assert result.evicted_ref == "output.txt"


@pytest.mark.asyncio
@pytest.mark.usefixtures("_mock_should_filter", "_mock_detect_non_structural")
async def test_eviction_no_executor_no_file_hint():
    """Without executor, no file_path hint should appear."""
    result = await maybe_evict_large_output("x" * 50000)
    assert isinstance(result, EvictionResult)
    assert "Full content saved to sandbox storage" not in result.text
    assert "LARGE OUTPUT TRUNCATED" in result.text
    assert result.evicted_ref is None


@pytest.mark.asyncio
@pytest.mark.usefixtures("_mock_should_filter", "_mock_detect_non_structural")
async def test_eviction_file_save_failure_still_has_preview(mock_executor):
    """If file save fails, preview should still be returned without file hint."""
    with patch(
        "myrm_agent_harness.agent.meta_tools.bash._output_eviction._save_to_file",
        side_effect=OSError("disk full"),
    ):
        result = await maybe_evict_large_output("x" * 50000, mock_executor)
    assert isinstance(result, EvictionResult)
    assert "LARGE OUTPUT TRUNCATED" in result.text
    assert "Full content saved to sandbox storage" not in result.text
    assert result.evicted_ref is None


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
    assert 'path=".context/session123/evicted/output_abc.txt"' in result.text
    assert "offset=" in result.text
    assert result.evicted_ref == "output_abc.txt"


@pytest.mark.asyncio
async def test_eviction_skips_small_output():
    """Small output should pass through unchanged."""
    result = await maybe_evict_large_output("small output")
    assert isinstance(result, EvictionResult)
    assert result.text == "small output"
    assert result.evicted_ref is None


@pytest.mark.asyncio
@pytest.mark.usefixtures("_mock_should_filter", "_mock_detect_non_structural")
async def test_eviction_no_session_skips_file_persist(mock_executor):
    """Without session_id, large output is preview-only (no GUI evicted ref)."""
    with patch(
        "myrm_agent_harness.agent.meta_tools.bash._output_eviction._get_session_id",
        return_value=None,
    ):
        result = await maybe_evict_large_output("x" * 50000, mock_executor)

    assert result.evicted_ref is None
    assert "LARGE OUTPUT TRUNCATED" in result.text
    mock_executor.write_file.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.usefixtures("_mock_should_filter")
async def test_eviction_structural_content_preview(mock_executor):
    """Structural JSON content uses structural filter summary path."""
    payload = '{"items": [' + '{"id": 1},' * 500 + '{"id": 999}]}'
    with (
        patch(
            "myrm_agent_harness.agent.meta_tools.bash._output_eviction._save_to_file",
            return_value=".context/s1/evicted/output_ab12cd34.txt",
        ),
        patch(
            "myrm_agent_harness.agent.meta_tools.bash._output_eviction.detect_content_type",
            return_value="json",
        ),
    ):
        result = await maybe_evict_large_output(payload, mock_executor)

    assert "LARGE OUTPUT TRUNCATED" in result.text or "structure" in result.text.lower()
    assert result.evicted_ref == "output_ab12cd34.txt"


def test_get_session_id_returns_none_on_error():
    from myrm_agent_harness.agent.meta_tools.bash import _output_eviction as mod

    with patch(
        "myrm_agent_harness.agent.context_management.infra.session_lock.get_current_chat_id",
        side_effect=RuntimeError("no session context"),
    ):
        assert mod._get_session_id() is None


@pytest.mark.asyncio
@pytest.mark.usefixtures("_mock_should_filter", "_mock_detect_non_structural")
async def test_save_to_file_persists_with_session(mock_executor):
    from myrm_agent_harness.agent.meta_tools.bash import _output_eviction as mod

    with (
        patch.object(mod, "_get_session_id", return_value="session_save"),
        patch(
            "myrm_agent_harness.runtime.execution_paths.get_evicted_output_path",
            return_value="/ws/.context/session_save/evicted/output_abcd1234.txt",
        ),
        patch(
            "myrm_agent_harness.runtime.execution_paths.get_workspace_relative_path",
            return_value=".context/session_save/evicted/output_abcd1234.txt",
        ),
        patch(
            "myrm_agent_harness.runtime.execution_paths.ensure_context_dir_exists",
        ),
    ):
        rel = await mod._save_to_file(mock_executor, "payload")

    assert rel == ".context/session_save/evicted/output_abcd1234.txt"
    mock_executor.write_file.assert_awaited_once()
