"""Tests for verification orchestration — _parse_verdict, VerificationVerdict, run_with_verification."""

from __future__ import annotations

import time
from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.agent.sub_agents._orchestrator_verification import (
    VerificationVerdict,
    _parse_verdict,
    run_with_verification,
)
from myrm_agent_harness.agent.sub_agents.types import SubagentConfig, SubAgentResult, SubAgentStatus


_GET_EXECUTOR_PATH = "myrm_agent_harness.toolkits.code_execution.executors.base.get_executor"


def _mock_executor(*, has_executed: bool = True) -> MagicMock:
    """Create a mock executor that reports code execution status."""
    executor = MagicMock()
    executor.has_executed_code = has_executed
    return executor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(task_id: str = "t1", agent_type: str = "worker", result: str = "done") -> SubAgentResult:
    return SubAgentResult(
        success=True, task_id=task_id, agent_type=agent_type,
        result=result, completed_at=time.time(), status=SubAgentStatus.COMPLETED,
    )


def _fail(task_id: str = "t1", agent_type: str = "worker", error: str = "boom") -> SubAgentResult:
    return SubAgentResult(
        success=False, task_id=task_id, agent_type=agent_type,
        error=error, completed_at=time.time(), status=SubAgentStatus.FAILED,
    )


def _verdict_json(verdict: str = "PASS", summary: str = "ok STDOUT", confidence: str = "HIGH",
                   findings: str = "[]") -> str:
    return f'{{"verdict": "{verdict}", "summary": "{summary}", "confidence": "{confidence}", "findings": {findings}}}'


# ---------------------------------------------------------------------------
# VerificationVerdict
# ---------------------------------------------------------------------------


class TestVerificationVerdict:
    def test_frozen_immutability(self):
        v = VerificationVerdict(passed=True, summary="ok", confidence="HIGH", findings=[], raw="")
        with pytest.raises(FrozenInstanceError):
            v.passed = False  # type: ignore[misc]

    def test_slots(self):
        v = VerificationVerdict(passed=True, summary="ok", confidence="HIGH", findings=[], raw="x")
        assert not hasattr(v, "__dict__")

    def test_fields(self):
        findings = [{"severity": "CRITICAL", "description": "NPE"}]
        v = VerificationVerdict(passed=False, summary="bad", confidence="LOW", findings=findings, raw="raw")
        assert v.passed is False
        assert v.summary == "bad"
        assert v.confidence == "LOW"
        assert len(v.findings) == 1
        assert v.raw == "raw"


# ---------------------------------------------------------------------------
# _parse_verdict
# ---------------------------------------------------------------------------


class TestParseVerdict:
    def test_standard_json_pass(self):
        v = _parse_verdict(_verdict_json("PASS", "All good STDOUT", "HIGH"))
        assert v.passed is True
        assert v.summary == "All good STDOUT"
        assert v.confidence == "HIGH"
        assert v.findings == []

    def test_standard_json_fail(self):
        v = _parse_verdict(_verdict_json("FAIL", "Bug found", "HIGH"))
        assert v.passed is False
        assert v.summary == "Bug found"

    def test_fail_with_findings(self):
        findings = '[{"severity": "CRITICAL", "description": "NPE in handler"}]'
        v = _parse_verdict(_verdict_json("FAIL", "Issues", "HIGH", findings))
        assert v.passed is False
        assert len(v.findings) == 1
        assert v.findings[0]["severity"] == "CRITICAL"
        assert v.findings[0]["description"] == "NPE in handler"

    def test_multiple_findings(self):
        findings = '[{"severity": "MAJOR", "description": "A"}, {"severity": "MINOR", "description": "B"}]'
        v = _parse_verdict(_verdict_json("FAIL", "Issues", "HIGH", findings))
        assert len(v.findings) == 2

    def test_markdown_fenced_json(self):
        raw = 'Here is my verdict:\n```json\n' + _verdict_json("PASS", "ok STDOUT") + '\n```\nEnd.'
        v = _parse_verdict(raw)
        assert v.passed is True

    def test_markdown_fenced_without_json_tag(self):
        raw = '```\n' + _verdict_json("FAIL") + '\n```'
        v = _parse_verdict(raw)
        assert v.passed is False

    def test_json_embedded_in_text(self):
        raw = 'Based on my analysis, ' + _verdict_json("PASS", "Looks good STDOUT") + ' that is my verdict.'
        v = _parse_verdict(raw)
        assert v.passed is True
        assert v.summary == "Looks good STDOUT"

    def test_gibberish_defaults_to_fail(self):
        v = _parse_verdict("I think everything looks fine but I cannot generate JSON")
        assert v.passed is False
        assert v.confidence == "LOW"
        assert "Unable to parse" in v.summary

    def test_empty_string_defaults_to_fail(self):
        v = _parse_verdict("")
        assert v.passed is False
        assert v.confidence == "LOW"

    def test_keyword_fallback_pass(self):
        raw = 'After analysis: "verdict": "PASS" — the code is correct. STDOUT'
        v = _parse_verdict(raw)
        assert v.passed is True
        assert v.confidence == "LOW"
        assert "keyword" in v.summary.lower()

    def test_keyword_fallback_no_space(self):
        raw = 'Result:"verdict":"PASS" end. STDOUT'
        v = _parse_verdict(raw)
        assert v.passed is True
        assert v.confidence == "LOW"

    def test_keyword_fail_not_triggered(self):
        """FAIL keyword does not have a special fallback — defaults to FAIL anyway."""
        raw = 'The "verdict": "FAIL" because reasons.'
        v = _parse_verdict(raw)
        assert v.passed is False

    def test_verdict_case_insensitive_json(self):
        v = _parse_verdict('{"verdict": "pass", "summary": "ok STDOUT", "confidence": "HIGH", "findings": []}')
        assert v.passed is True

    def test_verdict_with_extra_fields_ignored(self):
        raw = '{"verdict": "PASS", "summary": "ok STDOUT", "confidence": "HIGH", "findings": [], "extra_field": 123}'
        v = _parse_verdict(raw)
        assert v.passed is True

    def test_non_dict_findings_filtered(self):
        raw = '{"verdict": "FAIL", "summary": "x", "confidence": "LOW", "findings": ["string_item", {"severity": "MINOR", "description": "ok"}]}'
        v = _parse_verdict(raw)
        assert len(v.findings) == 1

    def test_raw_preserved(self):
        original = _verdict_json("PASS")
        v = _parse_verdict(original)
        assert v.raw == original

    def test_nested_json_braces(self):
        raw = '{"verdict": "FAIL", "summary": "x", "confidence": "HIGH", "findings": [{"severity": "CRITICAL", "description": "obj with {braces}"}]}'
        v = _parse_verdict(raw)
        assert v.passed is False
        assert len(v.findings) == 1

    def test_whitespace_around_verdict(self):
        v = _parse_verdict('  {"verdict": " PASS ", "summary": "ok STDOUT", "confidence": "HIGH", "findings": []}  ')
        assert v.passed is True

    def test_missing_confidence_defaults_to_unknown(self):
        v = _parse_verdict('{"verdict": "PASS", "summary": "ok", "findings": []}')
        assert v.confidence == "UNKNOWN"

    def test_missing_summary_defaults_to_empty(self):
        v = _parse_verdict('{"verdict": "PASS", "confidence": "HIGH", "findings": [], "STDOUT": "here"}')
        assert v.summary == ""


# ---------------------------------------------------------------------------
# run_with_verification
# ---------------------------------------------------------------------------


class TestRunWithVerification:
    @pytest.mark.asyncio
    @patch(_GET_EXECUTOR_PATH)
    async def test_pass_on_first_round(self, mock_get_executor):
        mock_get_executor.return_value = _mock_executor(has_executed=True)
        mgr = MagicMock()
        calls: list[str] = []

        async def _spawn(**kwargs):
            calls.append(kwargs["task_id"])
            if "worker" in kwargs["task_id"]:
                return _ok(kwargs["task_id"], kwargs["agent_type"], "work output")
            return _ok(kwargs["task_id"], kwargs["agent_type"], _verdict_json("PASS", "All good STDOUT", "HIGH"))

        mgr.spawn_child = _spawn
        w_cfg = SubagentConfig(system_prompt="worker")
        v_cfg = SubagentConfig(system_prompt="verifier")

        result = await run_with_verification(
            mgr, worker_type="w", worker_config=w_cfg, worker_task="do work",
            verifier_type="v", verifier_config=v_cfg, context={},
            tool_registry_getter=lambda: [], max_rounds=2,
        )
        assert result.success
        assert "PASS" in result.result
        assert len(calls) == 2  # 1 worker + 1 verifier

    @pytest.mark.asyncio
    @patch(_GET_EXECUTOR_PATH)
    async def test_fail_then_pass_on_retry(self, mock_get_executor):
        mock_get_executor.return_value = _mock_executor(has_executed=True)
        mgr = MagicMock()
        round_counter = {"worker": 0, "verifier": 0}

        async def _spawn(**kwargs):
            if "worker" in kwargs["task_id"]:
                round_counter["worker"] += 1
                return _ok(kwargs["task_id"], kwargs["agent_type"], f"work-r{round_counter['worker']}")
            round_counter["verifier"] += 1
            if round_counter["verifier"] == 1:
                findings = '[{"severity": "MAJOR", "description": "Missing edge case"}]'
                return _ok(kwargs["task_id"], kwargs["agent_type"],
                           _verdict_json("FAIL", "Issues found", "HIGH", findings))
            return _ok(kwargs["task_id"], kwargs["agent_type"],
                       _verdict_json("PASS", "Fixed STDOUT", "HIGH"))

        mgr.spawn_child = _spawn
        w_cfg = SubagentConfig(system_prompt="worker")
        v_cfg = SubagentConfig(system_prompt="verifier")

        result = await run_with_verification(
            mgr, worker_type="w", worker_config=w_cfg, worker_task="do work",
            verifier_type="v", verifier_config=v_cfg, context={},
            tool_registry_getter=lambda: [], max_rounds=3,
        )
        assert result.success
        assert "PASS" in result.result
        assert round_counter["worker"] == 2
        assert round_counter["verifier"] == 2

    @pytest.mark.asyncio
    async def test_all_rounds_fail(self):
        mgr = MagicMock()

        async def _spawn(**kwargs):
            if "worker" in kwargs["task_id"]:
                return _ok(kwargs["task_id"], kwargs["agent_type"], "work output")
            return _ok(kwargs["task_id"], kwargs["agent_type"],
                       _verdict_json("FAIL", "Still broken", "HIGH"))

        mgr.spawn_child = _spawn
        w_cfg = SubagentConfig(system_prompt="worker")
        v_cfg = SubagentConfig(system_prompt="verifier")

        result = await run_with_verification(
            mgr, worker_type="w", worker_config=w_cfg, worker_task="do work",
            verifier_type="v", verifier_config=v_cfg, context={},
            tool_registry_getter=lambda: [], max_rounds=2,
        )
        assert "FAIL after 2 round(s)" in result.result
        assert result.success is False, "Verification failure must propagate success=False"

    @pytest.mark.asyncio
    async def test_worker_failure_aborts(self):
        mgr = MagicMock()

        async def _spawn(**kwargs):
            return _fail(kwargs["task_id"], kwargs["agent_type"], "worker crashed")

        mgr.spawn_child = _spawn
        w_cfg = SubagentConfig(system_prompt="worker")
        v_cfg = SubagentConfig(system_prompt="verifier")

        result = await run_with_verification(
            mgr, worker_type="w", worker_config=w_cfg, worker_task="do work",
            verifier_type="v", verifier_config=v_cfg, context={},
            tool_registry_getter=lambda: [],
        )
        assert not result.success
        assert "worker crashed" in result.error

    @pytest.mark.asyncio
    async def test_verifier_failure_aborts(self):
        mgr = MagicMock()
        call_count = 0

        async def _spawn(**kwargs):
            nonlocal call_count
            call_count += 1
            if "worker" in kwargs["task_id"]:
                return _ok(kwargs["task_id"], kwargs["agent_type"], "work done")
            return _fail(kwargs["task_id"], kwargs["agent_type"], "verifier crashed")

        mgr.spawn_child = _spawn
        w_cfg = SubagentConfig(system_prompt="worker")
        v_cfg = SubagentConfig(system_prompt="verifier")

        result = await run_with_verification(
            mgr, worker_type="w", worker_config=w_cfg, worker_task="do work",
            verifier_type="v", verifier_config=v_cfg, context={},
            tool_registry_getter=lambda: [],
        )
        assert "FAIL after" in result.result

    @pytest.mark.asyncio
    async def test_max_rounds_clamped_to_one(self):
        mgr = MagicMock()

        async def _spawn(**kwargs):
            if "worker" in kwargs["task_id"]:
                return _ok(kwargs["task_id"], kwargs["agent_type"], "work")
            return _ok(kwargs["task_id"], kwargs["agent_type"],
                       _verdict_json("FAIL", "fail", "HIGH"))

        mgr.spawn_child = _spawn
        w_cfg = SubagentConfig(system_prompt="worker")
        v_cfg = SubagentConfig(system_prompt="verifier")

        result = await run_with_verification(
            mgr, worker_type="w", worker_config=w_cfg, worker_task="do work",
            verifier_type="v", verifier_config=v_cfg, context={},
            tool_registry_getter=lambda: [], max_rounds=0,
        )
        assert "FAIL after 1 round(s)" in result.result

    @pytest.mark.asyncio
    @patch(_GET_EXECUTOR_PATH)
    async def test_custom_verifier_task_template(self, mock_get_executor):
        mock_get_executor.return_value = _mock_executor(has_executed=True)
        mgr = MagicMock()
        captured_desc: list[str] = []

        async def _spawn(**kwargs):
            captured_desc.append(kwargs["task_description"])
            if "worker" in kwargs["task_id"]:
                return _ok(kwargs["task_id"], kwargs["agent_type"], "my-output")
            return _ok(kwargs["task_id"], kwargs["agent_type"],
                       _verdict_json("PASS"))

        mgr.spawn_child = _spawn
        w_cfg = SubagentConfig(system_prompt="worker")
        v_cfg = SubagentConfig(system_prompt="verifier")

        await run_with_verification(
            mgr, worker_type="w", worker_config=w_cfg, worker_task="do work",
            verifier_type="v", verifier_config=v_cfg, context={},
            tool_registry_getter=lambda: [],
            verifier_task_template="CHECK THIS: {worker_result}",
        )
        assert "CHECK THIS: my-output" in captured_desc[1]

    @pytest.mark.asyncio
    @patch(_GET_EXECUTOR_PATH)
    async def test_retry_feedback_contains_findings(self, mock_get_executor):
        mock_get_executor.return_value = _mock_executor(has_executed=True)
        mgr = MagicMock()
        worker_tasks: list[str] = []

        async def _spawn(**kwargs):
            if "worker" in kwargs["task_id"]:
                worker_tasks.append(kwargs["task_description"])
                return _ok(kwargs["task_id"], kwargs["agent_type"], "work")
            if len(worker_tasks) == 1:
                return _ok(kwargs["task_id"], kwargs["agent_type"],
                           _verdict_json("FAIL", "bug", "HIGH",
                                         '[{"severity": "CRITICAL", "description": "null check missing"}]'))
            return _ok(kwargs["task_id"], kwargs["agent_type"], _verdict_json("PASS"))

        mgr.spawn_child = _spawn
        w_cfg = SubagentConfig(system_prompt="worker")
        v_cfg = SubagentConfig(system_prompt="verifier")

        await run_with_verification(
            mgr, worker_type="w", worker_config=w_cfg, worker_task="original task",
            verifier_type="v", verifier_config=v_cfg, context={},
            tool_registry_getter=lambda: [], max_rounds=3,
        )
        assert len(worker_tasks) >= 2
        assert "null check missing" in worker_tasks[1]
        assert "original task" in worker_tasks[1]

    @pytest.mark.asyncio
    @patch(_GET_EXECUTOR_PATH)
    async def test_dict_return_from_spawn_child(self, mock_get_executor):
        mock_get_executor.return_value = _mock_executor(has_executed=True)
        mgr = MagicMock()

        async def _spawn(**kwargs):
            if "worker" in kwargs["task_id"]:
                return {"success": True, "result": "dict-output"}
            return {"success": True, "result": _verdict_json("PASS")}

        mgr.spawn_child = _spawn
        w_cfg = SubagentConfig(system_prompt="worker")
        v_cfg = SubagentConfig(system_prompt="verifier")

        result = await run_with_verification(
            mgr, worker_type="w", worker_config=w_cfg, worker_task="do work",
            verifier_type="v", verifier_config=v_cfg, context={},
            tool_registry_getter=lambda: [],
        )
        assert result.success
        assert "PASS" in result.result

    @pytest.mark.asyncio
    async def test_dict_worker_failure(self):
        mgr = MagicMock()

        async def _spawn(**kwargs):
            return {"success": False, "result": ""}

        mgr.spawn_child = _spawn
        w_cfg = SubagentConfig(system_prompt="worker")
        v_cfg = SubagentConfig(system_prompt="verifier")

        result = await run_with_verification(
            mgr, worker_type="w", worker_config=w_cfg, worker_task="do work",
            verifier_type="v", verifier_config=v_cfg, context={},
            tool_registry_getter=lambda: [],
        )
        assert not result.success

    @pytest.mark.asyncio
    @patch(_GET_EXECUTOR_PATH)
    async def test_verification_metadata_in_pass_result(self, mock_get_executor):
        mock_get_executor.return_value = _mock_executor(has_executed=True)
        mgr = MagicMock()

        async def _spawn(**kwargs):
            if "worker" in kwargs["task_id"]:
                return _ok(kwargs["task_id"], kwargs["agent_type"], "done")
            return _ok(kwargs["task_id"], kwargs["agent_type"],
                       _verdict_json("PASS", "ok STDOUT", "MEDIUM"))

        mgr.spawn_child = _spawn
        w_cfg = SubagentConfig(system_prompt="worker")
        v_cfg = SubagentConfig(system_prompt="verifier")

        result = await run_with_verification(
            mgr, worker_type="w", worker_config=w_cfg, worker_task="do work",
            verifier_type="v", verifier_config=v_cfg, context={},
            tool_registry_getter=lambda: [],
        )
        assert "Verification: PASS" in result.result
        assert "round 1/2" in result.result
        assert "confidence=MEDIUM" in result.result

    @pytest.mark.asyncio
    @patch(_GET_EXECUTOR_PATH)
    async def test_tool_call_verdict_used_when_present(self, mock_get_executor):
        """When verifier sets _verifier_verdict via tool call, it takes precedence over text parsing."""
        mock_get_executor.return_value = _mock_executor(has_executed=True)
        mgr = MagicMock()

        async def _spawn(**kwargs):
            if "worker" in kwargs["task_id"]:
                return _ok(kwargs["task_id"], kwargs["agent_type"], "work done")
            ctx = kwargs.get("context", {})
            ctx["_verifier_verdict"] = VerificationVerdict(
                passed=True,
                summary="All checks passed via tool",
                confidence="HIGH",
                findings=[],
                raw="[Submitted via Tool Call]",
            )
            return _ok(kwargs["task_id"], kwargs["agent_type"], "irrelevant text")

        mgr.spawn_child = _spawn
        w_cfg = SubagentConfig(system_prompt="worker")
        v_cfg = SubagentConfig(system_prompt="verifier")

        result = await run_with_verification(
            mgr, worker_type="w", worker_config=w_cfg, worker_task="do work",
            verifier_type="v", verifier_config=v_cfg, context={},
            tool_registry_getter=lambda: [], max_rounds=2,
        )
        assert result.success
        assert "PASS" in result.result

    @pytest.mark.asyncio
    @patch(_GET_EXECUTOR_PATH)
    async def test_no_execution_rejects_pass_verdict(self, mock_get_executor):
        """Verifier that submits PASS without executing code should be rejected."""
        mock_get_executor.return_value = _mock_executor(has_executed=False)
        mgr = MagicMock()

        async def _spawn(**kwargs):
            if "worker" in kwargs["task_id"]:
                return _ok(kwargs["task_id"], kwargs["agent_type"], "work done")
            return _ok(kwargs["task_id"], kwargs["agent_type"],
                       _verdict_json("PASS", "Looks good STDOUT", "HIGH"))

        mgr.spawn_child = _spawn
        w_cfg = SubagentConfig(system_prompt="worker")
        v_cfg = SubagentConfig(system_prompt="verifier")

        result = await run_with_verification(
            mgr, worker_type="w", worker_config=w_cfg, worker_task="do work",
            verifier_type="v", verifier_config=v_cfg, context={},
            tool_registry_getter=lambda: [], max_rounds=1,
        )
        assert not result.success
        assert "did not execute any code" in result.result

    @pytest.mark.asyncio
    async def test_verification_metadata_in_fail_result(self):
        mgr = MagicMock()

        async def _spawn(**kwargs):
            if "worker" in kwargs["task_id"]:
                return _ok(kwargs["task_id"], kwargs["agent_type"], "work")
            return _ok(kwargs["task_id"], kwargs["agent_type"],
                       _verdict_json("FAIL", "bad", "HIGH"))

        mgr.spawn_child = _spawn
        w_cfg = SubagentConfig(system_prompt="worker")
        v_cfg = SubagentConfig(system_prompt="verifier")

        result = await run_with_verification(
            mgr, worker_type="w", worker_config=w_cfg, worker_task="do work",
            verifier_type="v", verifier_config=v_cfg, context={},
            tool_registry_getter=lambda: [], max_rounds=1,
        )
        assert "Verification: FAIL after 1 round(s)" in result.result
        assert result.success is False, "Verification failure must set success=False"
