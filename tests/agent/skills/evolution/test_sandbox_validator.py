from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.agent.skills.evolution.core.types import SkillRecord
from myrm_agent_harness.agent.skills.evolution.execution.sandbox_validator import (
    SandboxValidator,
)
from myrm_agent_harness.toolkits.code_execution.executors.base import ExecutionResult
from myrm_agent_harness.toolkits.code_execution.executors.test_executor import (
    TestExecutionResult,
)


@pytest.mark.asyncio
async def test_sandbox_validator_no_python_code():
    validator = SandboxValidator()
    skill = SkillRecord(
        skill_id="mock",
        name="mock",
        description="mock",
        content="No code here",
        path="",
        lineage=None,  # type: ignore
    )
    is_safe, _msg = await validator.dry_run_skill(skill)
    assert is_safe is True


@pytest.mark.asyncio
async def test_sandbox_validator_with_python_code_success():
    validator = SandboxValidator()
    skill = SkillRecord(
        skill_id="mock",
        name="mock",
        description="mock",
        content="```python\nprint('hello')\n```",
        path="",
        lineage=None,  # type: ignore
    )

    mock_result = TestExecutionResult(
        passed=True,
        stdout="ok",
        stderr="",
        returncode=0,
        timed_out=False,
        duration_seconds=0.1,
    )
    with patch.object(
        validator._test_executor, "run_tests", new_callable=AsyncMock
    ) as mock_run:
        mock_run.return_value = mock_result
        is_safe, _msg = await validator.dry_run_skill(skill)
        assert is_safe is True
        mock_run.assert_called_once()


@pytest.mark.asyncio
async def test_sandbox_validator_with_python_code_failure():
    validator = SandboxValidator()
    skill = SkillRecord(
        skill_id="mock",
        name="mock",
        description="mock",
        content="```python\nprint('hello'\n```",
        path="",
        lineage=None,  # type: ignore
    )

    mock_result = TestExecutionResult(
        passed=False,
        stdout="",
        stderr="SyntaxError",
        returncode=1,
        timed_out=False,
        duration_seconds=0.1,
    )
    with patch.object(
        validator._test_executor, "run_tests", new_callable=AsyncMock
    ) as mock_run:
        mock_run.return_value = mock_result
        is_safe, _msg = await validator.dry_run_skill(skill)
        assert is_safe is False
        mock_run.assert_not_called()

@pytest.mark.asyncio
async def test_sandbox_validator_with_verification_steps_success():
    validator = SandboxValidator()
    skill = SkillRecord(
        skill_id="mock",
        name="mock",
        description="mock",
        content="No python code",
        path="",
        lineage=None,  # type: ignore
        verification_steps=[{"command": "echo test"}]
    )

    mock_result = ExecutionResult(
        success=True,
        stdout="test",
        stderr="",
        error=None,
    )
    with patch("myrm_agent_harness.agent.skills.evolution.execution.sandbox_validator.LocalExecutor.execute_bash", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = mock_result
        is_safe, _msg = await validator.dry_run_skill(skill)
        assert is_safe is True
        mock_run.assert_called_once()

@pytest.mark.asyncio
async def test_sandbox_validator_with_verification_steps_failure():
    validator = SandboxValidator()
    skill = SkillRecord(
        skill_id="mock",
        name="mock",
        description="mock",
        content="No python code",
        path="",
        lineage=None,  # type: ignore
        verification_steps=[{"command": "echo test"}]
    )

    mock_result = ExecutionResult(
        success=False,
        stdout="",
        stderr="error",
        error="Execution failed",
    )
    with patch("myrm_agent_harness.agent.skills.evolution.execution.sandbox_validator.LocalExecutor.execute_bash", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = mock_result
        is_safe, _msg = await validator.dry_run_skill(skill)
        assert is_safe is False
        mock_run.assert_called_once()

@pytest.mark.asyncio
async def test_sandbox_validator_with_verification_steps_empty_command():
    validator = SandboxValidator()
    skill = SkillRecord(
        skill_id="mock",
        name="mock",
        description="mock",
        content="No python code",
        path="",
        lineage=None,  # type: ignore
        verification_steps=[{"command": ""}]
    )

    is_safe, _msg = await validator.dry_run_skill(skill)
    assert is_safe is True
