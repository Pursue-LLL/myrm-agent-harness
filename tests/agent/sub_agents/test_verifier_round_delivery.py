"""Focused tests for _verifier_round used by Cron post-run delivery assurance."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.sub_agents._verification_parsing import VerificationVerdict
from myrm_agent_harness.agent.sub_agents._verifier_round import (
    _build_verifier_tool_registry_getter,
    verify_worker_output,
)
from myrm_agent_harness.agent.sub_agents.types import SubAgentResult, SubAgentStatus, SubagentConfig, WorkspacePolicy


class _ReadonlyTool:
    readonly = True
    name = "file_read_tool"
    metadata: dict[str, object] = {}


class _MutatingMcpTool:
    is_mcp = True
    readonly = False
    name = "mcp_write_tool"
    metadata: dict[str, object] = {"is_mcp": True}


def test_build_verifier_tool_registry_getter_filters_mutating_mcp_and_adds_submit_verdict() -> None:
    context: dict[str, object] = {}
    getter = _build_verifier_tool_registry_getter(lambda: [_ReadonlyTool(), _MutatingMcpTool()], context)
    tools = getter()
    tool_names = [getattr(t, "name", "") for t in tools]
    assert "mcp_write_tool" not in tool_names
    assert "file_read_tool" in tool_names
    assert "submit_verdict" in tool_names

    submit = next(t for t in tools if getattr(t, "name", "") == "submit_verdict")
    submit.invoke(
        {
            "passed": True,
            "summary": "ok",
            "findings": [],
            "confidence": "HIGH",
        }
    )
    verdict = context.get("_verifier_verdict")
    assert isinstance(verdict, VerificationVerdict)
    assert verdict.passed is True


@pytest.mark.asyncio
async def test_verify_worker_output_returns_tool_submitted_verdict() -> None:
    mgr = MagicMock()
    v_cfg = SubagentConfig(system_prompt="verifier", workspace_policy=WorkspacePolicy.READ_ONLY_SANDBOX)
    context: dict[str, object] = {
        "_verifier_verdict": VerificationVerdict(
            passed=True,
            summary="Verified with evidence",
            confidence="HIGH",
            findings=[],
            raw="",
        ),
        "_verifier_has_executed_code": True,
    }

    async def _spawn(**_kwargs) -> SubAgentResult:
        return SubAgentResult(
            success=True,
            task_id="verify-check-1-adversarial-reviewer",
            agent_type="adversarial-reviewer",
            result="done",
            completed_at=0.0,
            status=SubAgentStatus.COMPLETED,
        )

    mgr.spawn_child = _spawn

    fake_executor = MagicMock()
    fake_executor.has_executed_code = True

    with patch(
        "myrm_agent_harness.toolkits.code_execution.executors.base.get_executor",
        return_value=fake_executor,
    ), patch(
        "myrm_agent_harness.toolkits.code_execution.executors.readonly_proxy.ReadonlyExecutorProxy",
        side_effect=lambda executor: executor,
    ), patch(
        "myrm_agent_harness.agent.skills.evolution.execution.executor_context.ExecutorContextManager",
    ) as mock_ctx_mgr:
        mock_ctx_mgr.return_value.__enter__ = MagicMock(return_value=None)
        mock_ctx_mgr.return_value.__exit__ = MagicMock(return_value=None)

        verdict = await verify_worker_output(
            mgr,
            worker_output="worker output",
            worker_type="worker",
            verifier_type="adversarial-reviewer",
            verifier_config=v_cfg,
            context=context,
            tool_registry_getter=lambda: [],
            verifier_task_template="Confirm output matches side effects.",
        )

    assert verdict.passed is True
    assert verdict.summary == "Verified with evidence"


@pytest.mark.asyncio
async def test_emit_verification_verdict_emits_when_sink_available() -> None:
    from myrm_agent_harness.agent.sub_agents._verification_parsing import _emit_verification_verdict

    sink = MagicMock()
    sink.emit = AsyncMock()
    verdict = VerificationVerdict(
        passed=False,
        summary="missing evidence",
        confidence="LOW",
        findings=[{"severity": "MAJOR", "description": "no tests run"}],
        raw="",
    )

    with patch(
        "myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink",
        return_value=sink,
    ):
        await _emit_verification_verdict(
            verdict=verdict,
            round_num=1,
            max_rounds=1,
            worker_type="worker",
            verifier_type="adversarial-reviewer",
            has_diff=True,
        )

    sink.emit.assert_awaited_once()
