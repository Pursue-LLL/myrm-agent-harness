"""Tests for security.audit module — record / get / reset + ContextVar isolation + decision classification."""

import ast
import asyncio
from pathlib import Path
from typing import get_args

import pytest

import myrm_agent_harness
from myrm_agent_harness.agent.security.audit import (
    DecisionKind,
    SecurityDecision,
    get_audit_entries,
    is_blocking_decision,
    is_policy_denial,
    record_decision,
    reset_audit_log,
)
from myrm_agent_harness.observability.metrics import security_metrics

_SRC_ROOT = Path(myrm_agent_harness.__file__).parent


class TestRecordAndGet:
    def test_record_single(self):
        reset_audit_log()
        record_decision("bash_code_execute_tool", "ALLOW", "capability fence passed")
        entries = get_audit_entries()
        assert len(entries) == 1
        assert entries[0].tool_name == "bash_code_execute_tool"
        assert entries[0].decision == "ALLOW"
        assert entries[0].tainted is False

    def test_record_multiple(self):
        reset_audit_log()
        record_decision("web_search", "ALLOW", "ok")
        record_decision("shell_exec", "DENY", "not allowed")
        record_decision("file_read", "CRON_DENY", "cron fail-closed")
        entries = get_audit_entries()
        assert len(entries) == 3
        assert [e.decision for e in entries] == ["ALLOW", "DENY", "CRON_DENY"]

    def test_record_tainted(self):
        reset_audit_log()
        record_decision("bash_code_execute_tool", "TAINT_ESCALATE", "session tainted", tainted=True)
        entries = get_audit_entries()
        assert entries[0].tainted is True

    def test_get_returns_copy(self):
        reset_audit_log()
        record_decision("t", "ALLOW", "ok")
        entries1 = get_audit_entries()
        entries2 = get_audit_entries()
        assert entries1 == entries2
        assert entries1 is not entries2


class TestReset:
    def test_reset_clears_log(self):
        reset_audit_log()
        record_decision("t", "ALLOW", "ok")
        assert len(get_audit_entries()) == 1
        reset_audit_log()
        assert len(get_audit_entries()) == 0

    def test_reset_before_any_record(self):
        reset_audit_log()
        assert get_audit_entries() == []


class TestSecurityDecisionDataclass:
    def test_frozen(self):
        d = SecurityDecision(tool_name="t", decision="ALLOW", reason="ok")
        with pytest.raises(AttributeError):
            d.tool_name = "x"  # type: ignore[misc]

    def test_to_dict(self):
        d = SecurityDecision(
            tool_name="bash",
            decision="DENY",
            reason="blocked",
            tainted=True,
            timestamp=1000.1234,
        )
        result = d.to_dict()
        assert result["tool"] == "bash"
        assert result["decision"] == "DENY"
        assert result["reason"] == "blocked"
        assert result["tainted"] is True
        assert result["ts"] == 1000.123


class TestToolCallId:
    def test_record_with_tool_call_id(self):
        reset_audit_log()
        record_decision("bash", "DENY", "blocked", tool_call_id="call-1")
        entries = get_audit_entries()
        assert entries[0].tool_call_id == "call-1"

    def test_to_dict_includes_tool_call_id(self):
        d = SecurityDecision(
            tool_name="bash",
            decision="DENY",
            reason="blocked",
            tainted=True,
            tool_call_id="call-9",
            timestamp=1000.1234,
        )
        result = d.to_dict()
        assert result["tool_call_id"] == "call-9"

    def test_to_dict_omits_empty_tool_call_id(self):
        d = SecurityDecision(tool_name="bash", decision="ALLOW", reason="ok", timestamp=1000.0)
        result = d.to_dict()
        assert "tool_call_id" not in result


class TestContextVarIsolation:
    @pytest.mark.asyncio
    async def test_isolation_across_tasks(self):
        """Audit logs in different asyncio tasks are isolated via ContextVar."""
        results: dict[str, list[SecurityDecision]] = {}

        async def task_a():
            reset_audit_log()
            record_decision("tool_a", "ALLOW", "from task A")
            record_decision("tool_a2", "DENY", "from task A")
            results["a"] = get_audit_entries()

        async def task_b():
            reset_audit_log()
            record_decision("tool_b", "CRON_DENY", "from task B")
            results["b"] = get_audit_entries()

        await asyncio.gather(asyncio.create_task(task_a()), asyncio.create_task(task_b()))

        assert len(results["a"]) == 2
        assert results["a"][0].tool_name == "tool_a"
        assert results["a"][1].tool_name == "tool_a2"

        assert len(results["b"]) == 1
        assert results["b"][0].tool_name == "tool_b"
        assert results["b"][0].decision == "CRON_DENY"


class TestAutoInitOnFirstRecord:
    def test_record_without_reset(self):
        """record_decision auto-initializes the ContextVar if not set."""
        record_decision("auto_init", "ALLOW", "should not crash")
        entries = get_audit_entries()
        assert any(e.tool_name == "auto_init" for e in entries)


class TestLookupErrorBranches:
    def test_get_audit_entries_on_fresh_log(self):
        """get_audit_entries returns [] after reset."""
        reset_audit_log()
        result = get_audit_entries()
        assert result == []

    def test_record_decision_on_fresh_log(self):
        """record_decision works on a freshly reset log."""
        reset_audit_log()
        record_decision("fresh_tool", "DENY", "fresh context test")
        result = get_audit_entries()
        assert len(result) == 1
        assert result[0].tool_name == "fresh_tool"

    def test_record_decision_auto_initializes(self):
        """record_decision auto-initializes ContextVar when not previously set."""
        import contextvars

        ctx = contextvars.Context()

        def _run():
            record_decision("ctx_tool", "ALLOW", "auto-init in clean context")
            return get_audit_entries()

        result = ctx.run(_run)
        assert len(result) == 1
        assert result[0].tool_name == "ctx_tool"

    def test_get_audit_entries_returns_empty_in_clean_context(self):
        """get_audit_entries returns [] in a brand-new Context (no prior set)."""
        import contextvars

        ctx = contextvars.Context()

        def _run():
            return get_audit_entries()

        result = ctx.run(_run)
        assert result == []


def _recorded_decision_names() -> dict[str, str]:
    """Every decision name a source file passes to ``record_decision`` as a literal, with one place that does."""
    names: dict[str, str] = {}
    for path in sorted(_SRC_ROOT.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        if "record_decision(" not in source:
            continue
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call) and _callee_name(node) == "record_decision":
                for name in _decision_literals(node):
                    names.setdefault(name, f"{path.relative_to(_SRC_ROOT)}:{node.lineno}")
    return names


def _callee_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else None


def _decision_literals(call: ast.Call) -> list[str]:
    """The decision names a call can pass: a constant, or both arms of a conditional. A variable passes none."""
    if len(call.args) >= 2:
        argument: ast.expr | None = call.args[1]
    else:
        argument = next((kw.value for kw in call.keywords if kw.arg == "decision"), None)
    arms = [argument.body, argument.orelse] if isinstance(argument, ast.IfExp) else [argument]
    return [arm.value for arm in arms if isinstance(arm, ast.Constant) and isinstance(arm.value, str)]


class TestDecisionKindCompleteness:
    def test_every_literal_decision_a_call_site_records_is_declared(self) -> None:
        recorded = _recorded_decision_names()
        # A scanner that finds nothing would pass vacuously.
        assert {"CRON_DENY", "SSRF_BLOCKED", "OUTBOUND_DENY", "TIMEOUT_DENIED"} <= recorded.keys()

        declared = set(get_args(DecisionKind))
        undeclared = {name: where for name, where in recorded.items() if name not in declared}
        assert not undeclared, f"record_decision call sites use names missing from DecisionKind: {undeclared}"


# Decisions that stopped the action they were about. A decision whose name carries a stop marker but
# is absent here has to be an escalation to an approval prompt, never a silent omission.
_STOPPED = frozenset(
    {
        "DENY",
        "CRON_DENY",
        "LLM_REVIEW_DENY",
        "SUBAGENT_AUTO_DENY",
        "OUTBOUND_DENY",
        "SHELL_ESCALATION_DENY",
        "OPERATOR_AS_KEY_DENY",
        "INGRESS_FENCE_DENY",
        "INGRESS_FENCE_YOLO_BLOCKED",
        "YOLO_DENY_OVERRIDE",
        "READONLY_RESEARCH_LEASE_BLOCKED",
        "ESTOP_BLOCKED",
        "SSRF_BLOCKED",
        "INSECURE_REDIRECT_BLOCKED",
        "SKILL_HOOK_BLOCK",
        "HOOK_BLOCKED",
        "POST_HOOK_BLOCKED",
        "GUARDRAIL_BLOCKED",
        "CLARIFICATION_GUARD_BLOCKED",
        "PII_BLOCKED",
        "PII_BLOCKED_REDACTED",
        "INJECTION_BLOCKED",
        "DANGEROUS_INTENT_BLOCKED",
        "MISSING_SEMANTICS_BLOCKED",
        "CREDENTIAL_LEAK_BLOCKED",
        "NO_CONTEXT_DENIED",
        "TIMEOUT_DENIED",
        "USER_DENIED",
        "USER_REJECTED",
        "USER_EDIT_REJECTED",
        "DIGEST_MISMATCH_REJECT",
        "SCRIPT_INTEGRITY_REJECT",
        "SCRIPT_OPERAND_DRIFT_REJECT",
    }
)

# Named like a stop, yet the call goes on to an approval prompt.
_ESCALATIONS = (
    "PROTECTED_INSTRUCTION_ALLOWLIST_BLOCKED",
    "FINANCIAL_GATE_ALLOWLIST_BLOCKED",
    "IRREVERSIBLE_ACTION_ALLOWLIST_BLOCKED",
    "YOLO_FINANCIAL_GATE_BLOCKED",
    "YOLO_SOCIAL_IRREVERSIBLE_BLOCKED",
    "YOLO_DESTRUCTIVE_IRREVERSIBLE_BLOCKED",
)


class TestDecisionClassification:
    def test_blocking_decisions_are_exactly_the_stopped_actions(self) -> None:
        blocking = {kind for kind in get_args(DecisionKind) if is_blocking_decision(kind)}
        assert blocking == _STOPPED

    @pytest.mark.parametrize("decision", _ESCALATIONS)
    def test_an_escalation_is_no_stop_but_still_counts_as_a_denial_in_telemetry(self, decision: str) -> None:
        assert not is_blocking_decision(decision)
        assert is_policy_denial(decision)

    @pytest.mark.parametrize("decision", ["ALLOW", "ASK", "TAINT_ESCALATE", "USER_APPROVED", "OUTBOUND_UNCERTAIN"])
    def test_decisions_that_let_the_action_continue_are_neither(self, decision: str) -> None:
        assert not is_blocking_decision(decision)
        assert not is_policy_denial(decision)

    @pytest.mark.parametrize(
        "decision", ["DENY", "SSRF_BLOCKED", "PII_REDACTED", "CANARY_LEAKED", "CREDENTIAL_LEAK_DETECTED"]
    )
    def test_findings_of_block_deny_redact_or_leak_count_as_denials_in_telemetry(self, decision: str) -> None:
        assert is_policy_denial(decision)


class _FakeCounter:
    def __init__(self) -> None:
        self.labelled: list[dict[str, str]] = []

    def labels(self, **labels: str) -> "_FakeCounter":
        self.labelled.append(labels)
        return self

    def inc(self) -> None:
        pass


class TestPolicyDenialMetric:
    def test_a_denial_is_counted_under_the_first_finding_in_its_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        counter = _FakeCounter()
        monkeypatch.setattr(security_metrics, "policy_denial_total", counter)
        reset_audit_log()

        for decision in (
            "ALLOW",
            "CRON_DENY",
            "SSRF_BLOCKED",
            "PII_REDACTED",
            "PII_BLOCKED_REDACTED",
            "CANARY_LEAKED",
            "YOLO_FINANCIAL_GATE_BLOCKED",
        ):
            record_decision("tool", decision, "reason")  # type: ignore[arg-type]

        assert counter.labelled == [
            {"policy": "CRON_DENY", "action": "deny"},
            {"policy": "SSRF_BLOCKED", "action": "block"},
            {"policy": "PII_REDACTED", "action": "redact"},
            {"policy": "PII_BLOCKED_REDACTED", "action": "redact"},
            {"policy": "CANARY_LEAKED", "action": "leak"},
            {"policy": "YOLO_FINANCIAL_GATE_BLOCKED", "action": "block"},
        ]
