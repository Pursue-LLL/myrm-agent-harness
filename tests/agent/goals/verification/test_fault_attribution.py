from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.agent.goals.verification.base import ReviewSeverity
from myrm_agent_harness.agent.goals.verification.fault_attribution import (
    FaultKind,
    classify_fault,
)
from myrm_agent_harness.agent.goals.verification.shell import ShellCriterion
from myrm_agent_harness.toolkits.code_execution.executors.models import ExecutionResult


def test_classify_fault_oom_exit_code():
    res = classify_fault(exit_code=137, stdout="", stderr="")
    assert res.is_infra_fault is True
    assert res.kind == FaultKind.INFRA_ENVIRONMENT_FAILURE
    assert "137" in (res.guidance or "")


def test_classify_fault_network_and_services():
    cases = [
        ("Connection refused", "ECONNREFUSED"),
        ("Error: connect ECONNREFUSED 127.0.0.1:8080", "ECONNREFUSED"),
        ("ETIMEDOUT: connection timed out", "ETIMEDOUT"),
        ("502 Bad Gateway from upstream", "Bad Gateway"),
        ("docker: Cannot connect to the Docker daemon at unix:///var/run/docker.sock", "Docker"),
        ("redis.exceptions.ConnectionError: Error 61 connecting to localhost:6379", "Redis"),
        ("OSError: [Errno 48] Address already in use", "EADDRINUSE"),
        ("No space left on device", "ENOSPC"),
    ]
    for text, expected in cases:
        res = classify_fault(exit_code=1, stdout="", stderr=text)
        assert res.is_infra_fault is True, f"Failed for {text}"
        assert res.kind == FaultKind.INFRA_ENVIRONMENT_FAILURE
        assert res.guidance is not None


def test_classify_fault_pure_code_defect():
    code_error = "AssertionError: assert 1 == 2\nTypeError: unsupported operand type"
    res = classify_fault(exit_code=1, stdout="", stderr=code_error)
    assert res.is_infra_fault is False
    assert res.kind == FaultKind.CODE_DEFECT_FAILURE
    assert not res.is_infra


@pytest.mark.asyncio
async def test_shell_criterion_infra_fault_attribution():
    with patch("myrm_agent_harness.agent.goals.verification.shell.get_executor") as mock_get:
        executor = AsyncMock()
        mock_get.return_value = executor
        executor.execute_bash.return_value = ExecutionResult(
            exit_code=1,
            stdout="",
            stderr="redis.exceptions.ConnectionError: Connection refused",
        )

        criterion = ShellCriterion(command="pytest tests/")
        result = await criterion.verify()

        assert result.passed is False
        assert result.is_infra_fault is True
        assert result.fault_kind == FaultKind.INFRA_ENVIRONMENT_FAILURE.value
        assert result.fault_guidance is not None
        assert len(result.comments) == 1
        assert result.comments[0].severity == ReviewSeverity.CRITICAL
        assert "INFRASTRUCTURE FAULT" in result.comments[0].message
