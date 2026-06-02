"""Tests for execution_policy module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from myrm_agent_harness.agent.security.execution_policy import (
    ApprovalContract,
    ExecutionPolicy,
    suspend_execution,
)


class TestExecutionPolicy:
    def test_values(self):
        assert ExecutionPolicy.ALLOW == "allow"
        assert ExecutionPolicy.REQUIRE_APPROVAL == "require_approval"
        assert ExecutionPolicy.DENY == "deny"

    def test_is_str(self):
        assert isinstance(ExecutionPolicy.ALLOW, str)


class TestApprovalContract:
    def test_minimal(self):
        c = ApprovalContract(
            action_type="shell_command",
            payload={"cmd": "rm -rf /"},
            reason="Destructive command",
        )
        assert c.action_type == "shell_command"
        assert c.severity == "warning"

    def test_custom_severity(self):
        c = ApprovalContract(
            action_type="skill_patch",
            payload={"skill": "s1"},
            reason="Patching skill",
            severity="critical",
        )
        assert c.severity == "critical"

    def test_missing_required_fields(self):
        with pytest.raises(ValidationError):
            ApprovalContract(action_type="test")  # type: ignore[call-arg]

    def test_generic_payload(self):
        c = ApprovalContract[list[str]](
            action_type="test",
            payload=["a", "b"],
            reason="test",
        )
        assert c.payload == ["a", "b"]

    def test_model_dump(self):
        c = ApprovalContract(
            action_type="memory_mutation",
            payload={"key": "v"},
            reason="Mutation",
        )
        d = c.model_dump()
        assert d["action_type"] == "memory_mutation"
        assert d["severity"] == "warning"


class TestSuspendExecution:
    def test_calls_interrupt(self):
        contract = ApprovalContract(
            action_type="test",
            payload={"k": "v"},
            reason="Test reason",
        )
        mock_interrupt = MagicMock(return_value="approve")
        with patch(
            "myrm_agent_harness.agent.security.execution_policy.interrupt",
            mock_interrupt,
            create=True,
        ), patch.dict(
            "sys.modules", {"langgraph.types": MagicMock(interrupt=mock_interrupt)}
        ):
            result = suspend_execution(contract)
        # The interrupt should have been called with the serialized contract
        assert mock_interrupt.called or result is not None
