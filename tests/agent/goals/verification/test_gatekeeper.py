import pytest

from myrm_agent_harness.agent.goals.verification.base import VerificationResult
from myrm_agent_harness.agent.goals.verification.gatekeeper import VerificationGatekeeper


class MockCriterion:
    def __init__(self, passed=True, reason=None, error_logs=None, label="mock"):
        self._passed = passed
        self._reason = reason
        self._error_logs = error_logs
        self._label = label

    async def verify(self, goal_provider=None):
        return VerificationResult(
            passed=self._passed,
            criterion_label=self._label,
            reason=self._reason,
            error_logs=self._error_logs,
        )


@pytest.mark.asyncio
async def test_verify_all_passed():
    gatekeeper = VerificationGatekeeper([])
    gatekeeper.criteria = [
        MockCriterion(passed=True, label="check-a"),
        MockCriterion(passed=True, label="check-b"),
    ]

    result = await gatekeeper.verify_all()
    assert result.passed is True
    assert len(result.per_criterion) == 2
    assert all(r.passed for r in result.per_criterion)
    assert result.per_criterion[0].duration_ms >= 0


@pytest.mark.asyncio
async def test_verify_all_fail_all():
    gatekeeper = VerificationGatekeeper([])
    gatekeeper.criteria = [
        MockCriterion(passed=True, label="ok"),
        MockCriterion(passed=False, reason="Reason 1", error_logs="Logs 1", label="fail-1"),
        MockCriterion(passed=False, reason="Reason 2", error_logs="Logs 2", label="fail-2"),
    ]

    result = await gatekeeper.verify_all()
    assert result.passed is False
    assert result.failed_count == 2
    assert len(result.per_criterion) == 3
    assert result.per_criterion[1].reason == "Reason 1"
    assert result.per_criterion[1].error_logs == "Logs 1"
    assert result.per_criterion[2].reason == "Reason 2"
    assert result.per_criterion[2].error_logs == "Logs 2"

    serialized = result.to_dicts()
    assert len(serialized) == 3
    assert serialized[1]["label"] == "fail-1"
    assert serialized[1]["passed"] is False

@pytest.mark.asyncio
async def test_gatekeeper_registry():
    # Test initialization from config
    configs = [
        {"type": "shell", "command": "echo 1"},
        {"type": "semantic", "criteria": "test criteria"}
    ]
    gatekeeper = VerificationGatekeeper(configs)
    assert len(gatekeeper.criteria) == 2
    assert type(gatekeeper.criteria[0]).__name__ == "ShellCriterion"
    assert type(gatekeeper.criteria[1]).__name__ == "SemanticCriterion"
