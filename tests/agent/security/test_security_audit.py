"""Tests for security.audit module — record / get / reset + ContextVar isolation."""

import asyncio

import pytest

from myrm_agent_harness.agent.security.audit import (
    SecurityDecision,
    get_audit_entries,
    record_decision,
    reset_audit_log,
)


class TestRecordAndGet:
    def test_record_single(self):
        reset_audit_log()
        record_decision("bash_tool", "ALLOW", "capability fence passed")
        entries = get_audit_entries()
        assert len(entries) == 1
        assert entries[0].tool_name == "bash_tool"
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
        record_decision("bash_tool", "TAINT_ESCALATE", "session tainted", tainted=True)
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
        d = SecurityDecision(tool_name="bash", decision="DENY", reason="blocked", tainted=True, timestamp=1000.1234)
        result = d.to_dict()
        assert result["tool"] == "bash"
        assert result["decision"] == "DENY"
        assert result["reason"] == "blocked"
        assert result["tainted"] is True
        assert result["ts"] == 1000.123


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


class TestDecisionKindCompleteness:
    def test_all_used_decision_kinds_in_type(self):
        """Verify known decision kinds used in the codebase are valid."""
        from typing import get_args

        from myrm_agent_harness.agent.security.audit import DecisionKind

        valid_kinds = set(get_args(DecisionKind))
        used_kinds = [
            "ALLOW", "DENY", "ASK", "CRON_DENY", "TAINT_ESCALATE",
            "YOLO_AUTO_APPROVE", "LLM_REVIEW_ALLOW", "LLM_REVIEW_DENY",
            "LLM_REVIEW_UNCERTAIN", "SKILL_HOOK_BLOCK", "SKILL_HOOK_APPROVAL",
            "DOMAIN_RUNTIME_ALLOW", "ALLOWLIST_AUTO_APPROVE",
            "FREQUENCY_WARN", "FREQUENCY_BREAK",
        ]
        for kind in used_kinds:
            assert kind in valid_kinds, f"{kind} missing from DecisionKind"
