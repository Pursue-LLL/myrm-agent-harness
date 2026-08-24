"""Unit tests for Missing Semantics Contract Matrix & Fail-Closed Gates.

Verifies:
1. Contract matrix completeness and policy classification.
2. evaluate_missing_capability behaviors (FAIL_CLOSED raises, FAIL_FAST aborts, FALLBACK degrades).
3. safe_exec gate integration on sandbox absence.
4. LocalExecutor gate integration on sandbox absence for Python and Bash.
"""

import pytest
from myrm_agent_harness.core.security.missing_semantics import (
    MissingSemanticsBlockedError,
    MissingSemanticsPolicy,
    SemanticsCategory,
    evaluate_missing_capability,
    get_missing_semantics_matrix,
)
from myrm_agent_harness.core.security.safe_exec import safe_exec
from myrm_agent_harness.toolkits.code_execution.config import ExecutionConfig
from myrm_agent_harness.toolkits.code_execution.executors.local.executor import (
    LocalExecutor,
)
from myrm_agent_harness.toolkits.code_execution.executors.models import ExecutionContext


def test_missing_semantics_matrix_integrity():
    """Verify SSOT contract matrix covers core security and infra domains."""
    matrix = get_missing_semantics_matrix()
    assert SemanticsCategory.SANDBOX_ISOLATION in matrix
    assert SemanticsCategory.CREDENTIAL_VAULT in matrix
    assert SemanticsCategory.CORE_DATABASE in matrix
    assert SemanticsCategory.SECURITY_REVIEWER in matrix
    assert SemanticsCategory.READONLY_CACHE in matrix

    sandbox_contract = matrix[SemanticsCategory.SANDBOX_ISOLATION]
    assert sandbox_contract.policy == MissingSemanticsPolicy.FAIL_CLOSED
    assert "ERR_MISSING_SANDBOX_ISOLATION" in sandbox_contract.error_code

    db_contract = matrix[SemanticsCategory.CORE_DATABASE]
    assert db_contract.policy == MissingSemanticsPolicy.FAIL_FAST

    cache_contract = matrix[SemanticsCategory.READONLY_CACHE]
    assert cache_contract.policy == MissingSemanticsPolicy.FALLBACK


def test_evaluate_missing_capability_available():
    """Available capabilities should always PROCEED regardless of policy."""
    decision = evaluate_missing_capability(
        SemanticsCategory.SANDBOX_ISOLATION, is_available=True
    )
    assert decision.action == "PROCEED"
    assert decision.is_available is True


def test_evaluate_missing_capability_fail_closed():
    """Missing fail-closed capabilities must raise MissingSemanticsBlockedError."""
    with pytest.raises(MissingSemanticsBlockedError) as exc_info:
        evaluate_missing_capability(
            SemanticsCategory.SANDBOX_ISOLATION,
            is_available=False,
            detail="Docker daemon offline",
        )
    err = exc_info.value
    assert "ERR_MISSING_SANDBOX_ISOLATION" in str(err)
    assert "Docker daemon offline" in str(err)
    assert err.contract.policy == MissingSemanticsPolicy.FAIL_CLOSED


def test_evaluate_missing_capability_fail_fast():
    """Missing fail-fast capabilities should produce ABORT action."""
    decision = evaluate_missing_capability(
        SemanticsCategory.CORE_DATABASE, is_available=False
    )
    assert decision.action == "ABORT"
    assert decision.is_available is False
    assert decision.error_code == "ERR_MISSING_CORE_DATABASE"


def test_evaluate_missing_capability_fallback():
    """Missing fallback capabilities should produce FALLBACK action without exception."""
    decision = evaluate_missing_capability(
        SemanticsCategory.SECURITY_REVIEWER, is_available=False
    )
    assert decision.action == "FALLBACK"
    assert decision.is_available is False
    assert decision.error_code == "WARN_FALLBACK_DEFAULT_MODEL"


@pytest.mark.asyncio
async def test_safe_exec_sandbox_missing_fail_closed():
    """safe_exec must fail-closed when sandbox is required but missing."""
    with pytest.raises(MissingSemanticsBlockedError) as exc_info:
        await safe_exec(
            "echo 123",
            require_sandbox=True,
            sandbox_available=False,
        )
    assert "ERR_MISSING_SANDBOX_ISOLATION" in str(exc_info.value)


@pytest.mark.asyncio
async def test_local_executor_sandbox_missing_python_fail_closed():
    """LocalExecutor must block Python execution when sandbox is required but unavailable."""
    cfg = ExecutionConfig()
    cfg.local.require_sandbox_isolation = True
    cfg.local.sandbox_available = False

    executor = LocalExecutor(cfg)
    context = ExecutionContext(code="print('hello')", session_id="test_session")

    result = await executor.execute(context)
    assert result.success is False
    assert "ERR_MISSING_SANDBOX_ISOLATION" in (
        result.error or ""
    ) or "ERR_MISSING_SANDBOX_ISOLATION" in (result.stderr or "")
    assert "MissingDependencyFailClosedError" in (
        result.stderr or ""
    ) or "MissingSemanticsBlockedError" in (result.stderr or "")


@pytest.mark.asyncio
async def test_local_executor_sandbox_missing_bash_fail_closed():
    """LocalExecutor must block Bash execution when sandbox is required but unavailable."""
    cfg = ExecutionConfig()
    cfg.local.require_sandbox_isolation = True
    cfg.local.sandbox_available = False

    executor = LocalExecutor(cfg)
    context = ExecutionContext(code="ls -la", session_id="test_session")

    result = await executor.execute_bash(context)
    assert result.success is False
    assert "ERR_MISSING_SANDBOX_ISOLATION" in (
        result.error or ""
    ) or "ERR_MISSING_SANDBOX_ISOLATION" in (result.stderr or "")
    assert "MissingDependencyFailClosedError" in (
        result.stderr or ""
    ) or "MissingSemanticsBlockedError" in (result.stderr or "")
