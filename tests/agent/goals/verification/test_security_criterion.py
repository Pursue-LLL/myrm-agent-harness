from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.goals.verification.base import (
    ReviewComment,
    ReviewSeverity,
    VerificationResult,
)
from myrm_agent_harness.agent.goals.verification.gatekeeper import (
    VerificationGatekeeper,
)
from myrm_agent_harness.agent.goals.verification.security import (
    SecurityScanCriterion,
)


@pytest.mark.asyncio
async def test_security_scan_criterion_from_dict_and_registry() -> None:
    config = {
        "type": "security_scan",
        "scan_mode": "diff",
        "fail_on_severity": "critical",
        "timeout_seconds": 10,
        "target_paths": ["src/api/auth.py"],
        "poc_command": "curl http://localhost/exploit",
        "cwe_allowlist": ["CWE-89"],
        "criterion_label": "Auth Module Security Scan",
    }
    gatekeeper = VerificationGatekeeper(
        [config, {"type": "security", "scan_mode": "full"}]
    )
    assert len(gatekeeper.criteria) == 2
    assert isinstance(gatekeeper.criteria[0], SecurityScanCriterion)
    assert isinstance(gatekeeper.criteria[1], SecurityScanCriterion)

    crit: SecurityScanCriterion = gatekeeper.criteria[0]
    assert crit.scan_mode == "diff"
    assert crit.fail_on_severity == "critical"
    assert crit.timeout_seconds == 10
    assert crit.target_paths == ["src/api/auth.py"]
    assert crit.poc_command == "curl http://localhost/exploit"
    assert crit.cwe_allowlist == ["CWE-89"]
    assert crit.label == "Auth Module Security Scan"


@pytest.mark.asyncio
async def test_security_scan_criterion_delegates_to_goal_provider() -> None:
    crit = SecurityScanCriterion(
        scan_mode="diff",
        fail_on_severity="high",
        timeout_seconds=5,
        target_paths=["src/routes.py"],
    )

    mock_provider = MagicMock()
    mock_provider.evaluate_security_scan = AsyncMock(
        return_value=VerificationResult(
            passed=True,
            reason="Zero CVEs found in diff.",
        )
    )

    res = await crit.verify(mock_provider)
    assert res.passed is True
    assert res.criterion_label == "Security Scan Gate"
    mock_provider.evaluate_security_scan.assert_awaited_once_with(
        scan_mode="diff",
        target_paths=["src/routes.py"],
        fail_on_severity="high",
        poc_command=None,
        cwe_allowlist=[],
    )


@pytest.mark.asyncio
async def test_security_scan_criterion_timeout() -> None:
    crit = SecurityScanCriterion(timeout_seconds=1)

    async def slow_eval(*args: object, **kwargs: object) -> VerificationResult:
        await asyncio.sleep(2)
        return VerificationResult(passed=True)

    mock_provider = MagicMock()
    mock_provider.evaluate_security_scan = slow_eval

    res = await crit.verify(mock_provider)
    assert res.passed is False
    assert "timed out" in (res.reason or "").lower()


@pytest.mark.asyncio
async def test_security_scan_poc_exploit_fails_verification() -> None:
    crit = SecurityScanCriterion(poc_command="python exploit.py")

    mock_executor = MagicMock()
    mock_exec_result = MagicMock()
    mock_exec_result.exit_code = 0
    mock_exec_result.stdout = "Vulnerability exploited! Admin token leaked."
    mock_exec_result.stderr = ""
    mock_executor.execute_bash = AsyncMock(return_value=mock_exec_result)

    with patch(
        "myrm_agent_harness.agent.goals.verification.security.get_executor",
        return_value=mock_executor,
    ):
        res = await crit.verify(None)

    assert res.passed is False
    assert "reproduced successfully" in (res.reason or "")
    assert len(res.comments) == 1
    assert res.comments[0].severity == ReviewSeverity.CRITICAL


@pytest.mark.asyncio
async def test_security_scan_poc_evidence_truncation() -> None:
    crit = SecurityScanCriterion(poc_command="python flood.py")

    giant_output = "A" * 10000
    mock_executor = MagicMock()
    mock_exec_result = MagicMock()
    mock_exec_result.exit_code = 0
    mock_exec_result.stdout = giant_output
    mock_exec_result.stderr = ""
    mock_executor.execute_bash = AsyncMock(return_value=mock_exec_result)

    with patch(
        "myrm_agent_harness.agent.goals.verification.security.get_executor",
        return_value=mock_executor,
    ):
        res = await crit.verify(None)

    assert res.passed is False
    assert len(res.error_logs) < 5000
    assert "Omitted" in res.error_logs


@pytest.mark.asyncio
async def test_security_scan_poc_blocked_passes_verification() -> None:
    crit = SecurityScanCriterion(poc_command="python exploit.py")

    mock_executor = MagicMock()
    mock_exec_result = MagicMock()
    mock_exec_result.exit_code = 1
    mock_exec_result.stdout = ""
    mock_exec_result.stderr = "HTTP 403 Forbidden: Request Rejected"
    mock_executor.execute_bash = AsyncMock(return_value=mock_exec_result)

    with patch(
        "myrm_agent_harness.agent.goals.verification.security.get_executor",
        return_value=mock_executor,
    ):
        res = await crit.verify(None)

    assert res.passed is True
    assert "rejected or failed as expected" in (res.reason or "")
