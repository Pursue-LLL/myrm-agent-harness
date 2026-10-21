"""Integration test for Script Operand TOCTOU approval defense (CVE-2026-32921)."""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, ToolCall

from myrm_agent_harness.agent.middlewares._session_context import (
    set_approval_session,
    set_approval_user_id,
    set_workspace_root,
)
from myrm_agent_harness.agent.middlewares.approval._batch_decisions import (
    apply_approval_decisions,
)
from myrm_agent_harness.agent.middlewares.approval.batch_processor import (
    evaluate_tool_batch,
)
from myrm_agent_harness.agent.security.types import (
    PermissionAction,
    PermissionRule,
    SecurityConfig,
)


@pytest.mark.asyncio
async def test_script_operand_toctou_defense_lifecycle(tmp_path: Path) -> None:
    """Verify end-to-end TOCTOU defense: snapshot in batch evaluation, drift blocked on approve."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    script = workspace / "deploy.sh"
    script.write_text("#!/bin/bash\necho 'ORIGINAL_BENIGN'", encoding="utf-8")

    set_workspace_root(str(workspace))
    set_approval_user_id("test_user")
    set_approval_session("sess_toctou_test")

    config = SecurityConfig(
        ruleset=(
            PermissionRule("code_interpreter", "*", PermissionAction.ASK),
            PermissionRule("shell_exec", "*", PermissionAction.ASK),
        )
    )

    tool_call = ToolCall(
        name="bash_code_execute_tool",
        args={"command": f"bash {script.name}"},
        id="call_deploy_script",
    )

    # 1. Batch evaluation snapshots script operand and hides allow_always
    auto_approved, auto_denied, pending = await evaluate_tool_batch(
        tool_calls=[tool_call],
        config=config,
        is_cron=False,
        workspace_root=str(workspace),
        session_key="sess_toctou_test",
        args_hashes={0: "dummy_hash"},
    )

    assert len(auto_approved) == 0
    assert len(auto_denied) == 0
    assert len(pending) == 1

    idx, _tc, _perm_type, _reason, extra_ctx = pending[0]
    assert extra_ctx is not None
    assert extra_ctx.get("script_operand_path") == str(script.resolve())
    assert extra_ctx.get("script_operand_hash") is not None
    assert extra_ctx.get("hide_allow_always") is True

    last_ai_msg = AIMessage(content="", tool_calls=[tool_call])

    # 2. Simulate drift: file is modified while approval is pending
    script.write_text("#!/bin/bash\necho 'MALICIOUS_TAMPERED'", encoding="utf-8")

    # 3. User clicks approve
    decisions = [{"action_id": idx, "type": "approve"}]
    approved_calls, error_msgs, _ = await apply_approval_decisions(
        decisions=decisions,
        last_ai_msg=last_ai_msg,
        auto_denied=[],
        pending_approval=pending,
        interrupt_indices=[idx],
        args_hashes={0: "dummy_hash"},
        config=config,
    )

    # Execution must be BLOCKED: no approved calls, error tool message returned
    assert len(approved_calls) == 0
    assert len(error_msgs) == 1
    assert "Security Blocked" in error_msgs[0].content
    assert "modified before execution" in error_msgs[0].content
    assert error_msgs[0].status == "error"


@pytest.mark.asyncio
async def test_script_operand_untampered_passes_approval(tmp_path: Path) -> None:
    """Verify unchanged script executes normally upon approval."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    script = workspace / "safe.py"
    script.write_text("print('safe code')", encoding="utf-8")

    set_workspace_root(str(workspace))
    set_approval_user_id("test_user")
    set_approval_session("sess_safe_test")

    config = SecurityConfig(
        ruleset=(
            PermissionRule("code_interpreter", "*", PermissionAction.ASK),
            PermissionRule("shell_exec", "*", PermissionAction.ASK),
        )
    )

    tool_call = ToolCall(
        name="bash_code_execute_tool",
        args={"command": f"python3 {script.name}"},
        id="call_safe_script",
    )

    _, _, pending = await evaluate_tool_batch(
        tool_calls=[tool_call],
        config=config,
        is_cron=False,
        workspace_root=str(workspace),
        session_key="sess_safe_test",
        args_hashes={0: "dummy_hash"},
    )

    assert len(pending) == 1
    idx = pending[0][0]
    last_ai_msg = AIMessage(content="", tool_calls=[tool_call])

    # File is NOT mutated
    decisions = [{"action_id": idx, "type": "approve"}]
    approved_calls, error_msgs, _ = await apply_approval_decisions(
        decisions=decisions,
        last_ai_msg=last_ai_msg,
        auto_denied=[],
        pending_approval=pending,
        interrupt_indices=[idx],
        args_hashes={0: "dummy_hash"},
        config=config,
    )

    assert len(approved_calls) == 1
    assert approved_calls[0]["id"] == "call_safe_script"
    assert len(error_msgs) == 0
