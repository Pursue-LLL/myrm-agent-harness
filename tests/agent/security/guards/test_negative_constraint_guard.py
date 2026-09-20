"""Tests for NegativeConstraintComplianceGate and pre-call guard integration."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.errors.tool_error_category import ToolErrorCategory
from myrm_agent_harness.agent.middlewares._session_context import (
    get_active_negative_constraints,
    set_active_negative_constraints,
)
from myrm_agent_harness.agent.security.guards.negative_constraint_guard import (
    NegativeConstraint,
    NegativeConstraintComplianceGate,
    VetoAction,
    get_compliance_gate,
    reset_compliance_gate,
)


class TestNegativeConstraintComplianceGate:
    def setup_method(self) -> None:
        reset_compliance_gate()
        set_active_negative_constraints(None)

    def teardown_method(self) -> None:
        reset_compliance_gate()
        set_active_negative_constraints(None)

    def test_allow_when_no_active_constraints(self) -> None:
        gate = NegativeConstraintComplianceGate()
        verdict = gate.check("bash_tool", {"command": "rm -rf /tmp/test"}, [])
        assert verdict.action == VetoAction.ALLOW
        assert verdict.violated_rule is None

    def test_allow_when_tool_out_of_scope(self) -> None:
        constraint = NegativeConstraint(
            rule_id="veto-1",
            name="no-rm-rf",
            pattern="rm -rf",
            tool_scope="bash_tool",
            reason="Destructive command prohibited",
            remediation_advice="Use safe deletion via trash or python os.remove",
        )
        gate = NegativeConstraintComplianceGate()
        # file_read_tool is out of scope for bash_tool constraint
        verdict = gate.check("file_read_tool", {"path": "/tmp/rm -rf"}, [constraint])
        assert verdict.action == VetoAction.ALLOW

    def test_block_when_keyword_matches_in_scope(self) -> None:
        constraint = NegativeConstraint(
            rule_id="veto-1",
            name="no-any-type",
            pattern="Any",
            tool_scope="write_to_file,edit_file",
            reason="Strict typing policy: Any is forbidden",
            remediation_advice="Use concrete types or TypeVar",
        )
        gate = NegativeConstraintComplianceGate()
        verdict = gate.check("write_to_file", {"content": "def foo(x: Any) -> None: pass"}, [constraint])
        assert verdict.action == VetoAction.BLOCK
        assert verdict.violated_rule is not None
        assert verdict.violated_rule.rule_id == "veto-1"
        assert "no-any-type" in verdict.reason
        assert verdict.remediation_advice == "Use concrete types or TypeVar"
        assert verdict.retry_count == 1

    def test_block_with_regex_matching(self) -> None:
        constraint = NegativeConstraint(
            rule_id="veto-regex",
            name="no-eval-or-exec",
            pattern=r"\b(eval|exec)\s*\(",
            tool_scope="*",
            reason="Dynamic code execution is forbidden",
            remediation_advice="Use ast.literal_eval or safe dispatch",
            is_regex=True,
        )
        gate = NegativeConstraintComplianceGate()
        verdict = gate.check("run_script", {"code": "result = eval('1+1')"}, [constraint])
        assert verdict.action == VetoAction.BLOCK
        assert verdict.violated_rule is not None
        assert verdict.violated_rule.rule_id == "veto-regex"

    def test_circuit_break_after_repeated_retries(self) -> None:
        constraint = NegativeConstraint(
            rule_id="veto-loop",
            name="no-legacy-db",
            pattern="legacy_db_call",
            tool_scope="*",
            reason="Legacy database is deprecated",
            remediation_advice="Use modern repository layer",
        )
        gate = NegativeConstraintComplianceGate()

        # Attempt 1: Blocked
        v1 = gate.check("db_tool", {"query": "legacy_db_call()"}, [constraint])
        assert v1.action == VetoAction.BLOCK
        assert v1.retry_count == 1

        # Attempt 2: Blocked
        v2 = gate.check("db_tool", {"query": "legacy_db_call()"}, [constraint])
        assert v2.action == VetoAction.BLOCK
        assert v2.retry_count == 2

        # Attempt 3: Exceeds _MAX_IN_STEP_RETRIES (2) -> CIRCUIT_BREAK
        v3 = gate.check("db_tool", {"query": "legacy_db_call()"}, [constraint])
        assert v3.action == VetoAction.CIRCUIT_BREAK
        assert "repeatedly" in v3.reason
        assert v3.retry_count == 3

    def test_reset_counters_restores_allow_and_retry_flow(self) -> None:
        constraint = NegativeConstraint(
            rule_id="veto-reset",
            name="test-rule",
            pattern="bad_token",
            tool_scope="*",
        )
        gate = NegativeConstraintComplianceGate()
        gate.check("tool_a", {"val": "bad_token"}, [constraint])
        gate.check("tool_a", {"val": "bad_token"}, [constraint])
        v_blocked = gate.check("tool_a", {"val": "bad_token"}, [constraint])
        assert v_blocked.action == VetoAction.CIRCUIT_BREAK

        gate.reset_counters()
        v_after_reset = gate.check("tool_a", {"val": "bad_token"}, [constraint])
        assert v_after_reset.action == VetoAction.BLOCK
        assert v_after_reset.retry_count == 1


class TestNegativeConstraintIntegrationWithPreCallGuards:
    def setup_method(self) -> None:
        reset_compliance_gate()
        set_active_negative_constraints(None)

    def teardown_method(self) -> None:
        reset_compliance_gate()
        set_active_negative_constraints(None)

    @pytest.mark.asyncio
    async def test_run_pre_call_guards_blocks_on_veto(self) -> None:
        from unittest.mock import MagicMock
        from myrm_agent_harness.agent.middlewares.tooling._tool_guards import run_pre_call_guards

        constraint = NegativeConstraint(
            rule_id="veto-drop",
            name="no-drop-table",
            pattern="DROP TABLE",
            tool_scope="sql_tool",
            reason="DDL drop operations forbidden",
            remediation_advice="Soft delete or create migration branch",
        )
        set_active_negative_constraints([constraint])

        mock_request = MagicMock()
        mock_request.tool_call = {"args": {"query": "DROP TABLE users;"}}

        result = await run_pre_call_guards(
            request=mock_request,
            tool_name="sql_tool",
            tool_call_id="call-123",
            tool_args={"query": "DROP TABLE users;"},
        )

        assert hasattr(result, "content")
        assert "COMPLIANCE_ERROR" in str(result.content)
        assert "no-drop-table" in str(result.content)
        assert result.additional_kwargs.get("error_category") == ToolErrorCategory.GUARDRAIL_BLOCKED
