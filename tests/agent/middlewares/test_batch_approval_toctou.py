"""Integration test for Batch Approval TOCTOU Script Operand Drift Prevention.

Validates that when a script is snapshotted at approval interrupt time (TOC),
any modification to the script file prior to apply_approval_decisions (TOU)
results in automatic rejection with an artificial security blocked ToolMessage.
"""

from __future__ import annotations

import pytest
from pathlib import Path
from langchain_core.messages import AIMessage, ToolCall

from myrm_agent_harness.agent.middlewares.approval._batch_decisions import (
    apply_approval_decisions,
    build_interrupt_payload,
)
from myrm_agent_harness.agent.security.script_operand_verifier import (
    compute_file_content_digest,
)


@pytest.mark.asyncio
async def test_batch_approval_payload_includes_script_operand_meta(tmp_path: Path) -> None:
    """Validate build_batch_approval_interrupt_payload exposes scriptOperandPath/Hash."""
    script = tmp_path / "deploy.sh"
    script.write_text("#!/bin/sh\necho 'clean'")
    digest = compute_file_content_digest(str(script))
    assert digest is not None

    tool_call: ToolCall = {
        "name": "bash",
        "args": {"command": f"bash {script}"},
        "id": "call_123",
        "type": "tool_call",
    }

    extra_ctx = {
        "script_operand_path": str(script),
        "script_operand_hash": digest,
        "hide_allow_always": True,
    }

    pending_approval = [
        (0, tool_call, "bash", "Execute shell command", extra_ctx)
    ]

    payload, interrupt_indices = build_interrupt_payload(
        pending_approval=pending_approval,
        session_key="session_test",
        workspace_root=str(tmp_path),
    )

    assert interrupt_indices == [0]
    action_req = payload["actionRequests"][0]
    review_cfg = payload["reviewConfigs"][0]

    assert action_req["scriptOperandPath"] == str(script)
    assert action_req["scriptOperandHash"] == digest
    assert review_cfg["scriptOperandProtected"] is True
    assert review_cfg["hideAllowAlways"] is True


@pytest.mark.asyncio
async def test_apply_approval_blocks_toctou_tampered_script(tmp_path: Path) -> None:
    """Validate apply_approval_decisions blocks execution when script is modified before user approvals apply."""
    script = tmp_path / "build.py"
    script.write_text("print('legitimate build')")
    original_digest = compute_file_content_digest(str(script))
    assert original_digest is not None

    tool_call: ToolCall = {
        "name": "python",
        "args": {"command": f"python3 {script}"},
        "id": "call_tamper",
        "type": "tool_call",
    }

    extra_ctx = {
        "script_operand_path": str(script),
        "script_operand_hash": original_digest,
    }

    pending_approval = [
        (0, tool_call, "python", "Run python script", extra_ctx)
    ]

    # Malicious actor or concurrent process modifies the script before user clicks approve
    script.write_text("import os; os.system('malicious_payload')")

    decisions = [{"action_id": "call_tamper", "decision": "approve"}]
    ai_msg = AIMessage(content="", tool_calls=[tool_call])

    allowed, artificial_msgs, _ = await apply_approval_decisions(
        decisions=decisions,
        last_ai_msg=ai_msg,
        auto_denied=[],
        pending_approval=pending_approval,
        interrupt_indices=[0],
        args_hashes={0: "dummy_hash"},
    )

    # Allowed tools should be empty; tool should be blocked due to TOCTOU drift
    assert len(allowed) == 0
    assert len(artificial_msgs) == 1
    assert "Security Blocked" in str(artificial_msgs[0].content)
    assert "TOCTOU detected" in str(artificial_msgs[0].content)


@pytest.mark.asyncio
async def test_apply_approval_allows_unmodified_script(tmp_path: Path) -> None:
    """Validate apply_approval_decisions succeeds when script file remains strictly identical."""
    script = tmp_path / "safe.sh"
    script.write_text("echo 'verified'")
    original_digest = compute_file_content_digest(str(script))
    assert original_digest is not None

    tool_call: ToolCall = {
        "name": "bash",
        "args": {"command": f"bash {script}"},
        "id": "call_safe",
        "type": "tool_call",
    }

    extra_ctx = {
        "script_operand_path": str(script),
        "script_operand_hash": original_digest,
    }

    pending_approval = [
        (0, tool_call, "bash", "Run bash script", extra_ctx)
    ]

    decisions = [{"action_id": "call_safe", "decision": "approve"}]
    ai_msg = AIMessage(content="", tool_calls=[tool_call])

    allowed, artificial_msgs, _ = await apply_approval_decisions(
        decisions=decisions,
        last_ai_msg=ai_msg,
        auto_denied=[],
        pending_approval=pending_approval,
        interrupt_indices=[0],
        args_hashes={0: "dummy_hash"},
    )

    assert len(allowed) == 1
    assert allowed[0] == tool_call
    assert len(artificial_msgs) == 0
