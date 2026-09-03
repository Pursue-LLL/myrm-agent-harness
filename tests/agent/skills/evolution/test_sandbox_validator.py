from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.agent.skills.evolution.core.types import (
    EvolutionType,
    SkillLineage,
    SkillRecord,
)
from myrm_agent_harness.agent.skills.evolution.execution.hollow_detector import (
    HollowTestDetector,
)
from myrm_agent_harness.agent.skills.evolution.execution.sandbox_validator import (
    SandboxValidator,
)
from myrm_agent_harness.toolkits.code_execution.executors.base import ExecutionResult


def _create_mock_skill(content: str, verification_steps=None) -> SkillRecord:
    return SkillRecord(
        skill_id="mock_skill_1",
        name="Mock Skill",
        description="A test skill",
        content=content,
        path="",
        lineage=SkillLineage(evolution_type=EvolutionType.FIX, version=1),
        verification_steps=verification_steps or [],
    )


def test_hollow_test_detector_trivial_asserts():
    detector = HollowTestDetector()

    # Trivial assert True
    res1 = detector.analyze_python_code("assert True")
    assert res1.is_hollow is True
    assert "Trivial assertion detected" in res1.reasons[0]

    # Trivial identical compare
    res2 = detector.analyze_python_code("assert 1 == 1")
    assert res2.is_hollow is True

    # Genuine assertion
    res3 = detector.analyze_python_code("def test_calc():\n    assert calculate(2) == 4")
    assert res3.is_hollow is False
    assert res3.non_trivial_assert_count == 1


def test_hollow_test_detector_shell_commands():
    detector = HollowTestDetector()

    # Hollow echo / noop
    res1 = detector.analyze_shell_command("echo 'done'")
    assert res1.is_hollow is True

    res2 = detector.analyze_shell_command("exit 0")
    assert res2.is_hollow is True

    # Valid test command
    res3 = detector.analyze_shell_command("pytest tests/test_skill.py -v")
    assert res3.is_hollow is False


@pytest.mark.asyncio
async def test_sandbox_validator_prompt_skill_verified():
    validator = SandboxValidator()
    skill = _create_mock_skill(content="You are a helpful translation assistant.")
    proof = await validator.verify_skill_capsule(skill)

    assert proof.is_verified is True
    assert proof.hollow_detected is False
    assert proof.blast_radius["lines"] == 1


@pytest.mark.asyncio
async def test_sandbox_validator_rejects_hollow_python():
    validator = SandboxValidator()
    skill = _create_mock_skill(content="```python\nassert True\n```")
    proof = await validator.verify_skill_capsule(skill)

    assert proof.is_verified is False
    assert proof.hollow_detected is True
    assert "Hollow Test Rejected" in proof.verification_summary


@pytest.mark.asyncio
async def test_sandbox_validator_rejects_hollow_shell_step():
    validator = SandboxValidator()
    skill = _create_mock_skill(
        content="Clean content without python blocks",
        verification_steps=[{"command": "echo 'ok'"}],
    )
    proof = await validator.verify_skill_capsule(skill)

    assert proof.is_verified is False
    assert proof.hollow_detected is True
    assert "Hollow verification step detected" in proof.verification_summary


@pytest.mark.asyncio
async def test_sandbox_validator_with_valid_verification_steps_success():
    validator = SandboxValidator()
    skill = _create_mock_skill(
        content="Clean content",
        verification_steps=[{"command": "python test_runner.py"}],
    )

    mock_result = ExecutionResult(
        success=True,
        stdout="1 passed",
        stderr="",
        error=None,
    )
    with patch(
        "myrm_agent_harness.agent.skills.evolution.execution.sandbox_validator.LocalExecutor.execute_bash",
        new_callable=AsyncMock,
    ) as mock_run:
        mock_run.return_value = mock_result
        proof = await validator.verify_skill_capsule(skill)
        assert proof.is_verified is True
        assert proof.hollow_detected is False
        assert proof.success_streak >= 1
        mock_run.assert_called_once()
