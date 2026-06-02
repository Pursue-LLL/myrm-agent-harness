import pytest

from myrm_agent_harness.agent.goals.verification.base import VerificationResult
from myrm_agent_harness.agent.goals.verification.gatekeeper import VerificationGatekeeper


# Mock criteria for testing
class MockCriterion:
    def __init__(self, passed=True, reason=None, error_logs=None):
        self._passed = passed
        self._reason = reason
        self._error_logs = error_logs

    async def verify(self, goal_provider=None):
        return VerificationResult(
            passed=self._passed,
            reason=self._reason,
            error_logs=self._error_logs
        )

@pytest.mark.asyncio
async def test_verify_all_passed():
    gatekeeper = VerificationGatekeeper([])
    # Inject mock criteria manually since we don't want to rely on the registry for unit tests
    gatekeeper.criteria = [
        MockCriterion(passed=True),
        MockCriterion(passed=True)
    ]

    result = await gatekeeper.verify_all()
    assert result.passed is True
    assert result.reason is None
    assert result.error_logs is None

@pytest.mark.asyncio
async def test_verify_all_fail_all():
    gatekeeper = VerificationGatekeeper([])
    gatekeeper.criteria = [
        MockCriterion(passed=True),
        MockCriterion(passed=False, reason="Reason 1", error_logs="Logs 1"),
        MockCriterion(passed=False, reason="Reason 2", error_logs="Logs 2")
    ]

    result = await gatekeeper.verify_all()
    assert result.passed is False
    assert "Reason 1" in result.reason
    assert "Reason 2" in result.reason
    assert "Logs 1" in result.error_logs
    assert "Logs 2" in result.error_logs

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
