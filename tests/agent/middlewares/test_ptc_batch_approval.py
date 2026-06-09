from unittest.mock import patch

import pytest
from langchain_core.messages import ToolCall

from myrm_agent_harness.agent.middlewares.approval.batch_processor import evaluate_tool_batch
from myrm_agent_harness.agent.security.tool_registry import SafetyMetadata
from myrm_agent_harness.agent.security.types import PathPolicy, SecurityConfig


@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.security.tool_registry.get_ptc_safety_metadata")
@patch("myrm_agent_harness.agent.security.ptc_verifier.extract_ptc_intent")
async def test_evaluate_ptc_fast_path_auto_approve(mock_extract_intent, mock_get_meta):
    """Test that a purely read-only PTC call gets auto-approved."""
    # Setup mocks
    mock_extract_intent.return_value = ("mcp_github_skill", "read_file", {"path": "/workspace/repo"})

    # Return safety metadata (read-only, not open-world)
    safety_meta = SafetyMetadata(is_read_only=True, is_open_world=False, is_destructive=False, is_concurrent_safe=True)
    mock_get_meta.return_value = (safety_meta, {"readOnlyHint": True})

    config = SecurityConfig(auto_mode_enabled=False, path_policy=PathPolicy())
    tool_call = ToolCall(
        name="bash_code_execute_tool",
        args={"command": 'python -c "from skills.mcp_github_skill import _read_file; _read_file(path=\'/workspace/repo\')"'},
        id="call_123"
    )

    auto_approved, auto_denied, pending = await evaluate_tool_batch(
        tool_calls=[tool_call],
        config=config,
        is_cron=False,
        workspace_root="/workspace",
        session_key="test_sess",
        args_hashes={}
    )

    assert len(auto_approved) == 1
    assert len(auto_denied) == 0
    assert len(pending) == 0
    assert auto_approved[0][1].get("id") == "call_123"

@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.security.tool_registry.get_ptc_safety_metadata")
@patch("myrm_agent_harness.agent.security.ptc_verifier.extract_ptc_intent")
async def test_evaluate_ptc_destructive_is_pending(mock_extract_intent, mock_get_meta):
    """Test that a destructive PTC call remains in pending_approval with extra context."""
    # Setup mocks
    mock_extract_intent.return_value = ("mcp_github_skill", "write_file", {"path": "/workspace/repo/file.txt"})

    # Return safety metadata (destructive, not read-only)
    safety_meta = SafetyMetadata(is_read_only=False, is_open_world=False, is_destructive=True, is_concurrent_safe=False)
    mock_get_meta.return_value = (safety_meta, {"destructiveHint": True})

    config = SecurityConfig(auto_mode_enabled=False, path_policy=PathPolicy())
    tool_call = ToolCall(
        name="bash_code_execute_tool",
        args={"command": 'python -c "from skills.mcp_github_skill import _write_file; _write_file(path=\'/workspace/repo/file.txt\')"'},
        id="call_123"
    )

    auto_approved, auto_denied, pending = await evaluate_tool_batch(
        tool_calls=[tool_call],
        config=config,
        is_cron=False,
        workspace_root="/workspace",
        session_key="test_sess",
        args_hashes={}
    )

    assert len(auto_approved) == 0
    assert len(auto_denied) == 0
    assert len(pending) == 1

    _idx, _tc, _perm_type, _reason, extra_ctx = pending[0]
    assert extra_ctx is not None
    assert extra_ctx["ptc_tool_name_full"] == "ptc:mcp_github_skill.write_file"
    assert "ptc_annotations" in extra_ctx
    assert extra_ctx["ptc_annotations"] == {"destructiveHint": True}


@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.security.tool_registry.get_ptc_safety_metadata")
@patch("myrm_agent_harness.agent.security.ptc_verifier.extract_ptc_intent")
async def test_evaluate_ptc_contradictory_annotations_is_pending(mock_extract_intent, mock_get_meta):
    """Contradictory annotations (readOnly + destructive) stay pending in PTC path."""
    mock_extract_intent.return_value = ("mcp_buggy_skill", "trap_tool", {"path": "/workspace"})

    safety_meta = SafetyMetadata(
        is_read_only=True, is_open_world=False, is_destructive=True, is_concurrent_safe=True
    )
    mock_get_meta.return_value = (safety_meta, {"readOnlyHint": True, "destructiveHint": True})

    config = SecurityConfig(auto_mode_enabled=False, path_policy=PathPolicy())
    tool_call = ToolCall(
        name="bash_code_execute_tool",
        args={"command": 'python -c "from skills.mcp_buggy_skill import _trap_tool; _trap_tool(path=\'/workspace\')"'},
        id="call_trap",
    )

    auto_approved, auto_denied, pending = await evaluate_tool_batch(
        tool_calls=[tool_call],
        config=config,
        is_cron=False,
        workspace_root="/workspace",
        session_key="test_sess",
        args_hashes={},
    )

    assert len(auto_approved) == 0
    assert len(auto_denied) == 0
    assert len(pending) == 1
