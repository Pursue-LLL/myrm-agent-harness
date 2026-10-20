"""Tests for verification orchestration — _parse_verdict, VerificationVerdict, run_with_verification."""

from __future__ import annotations

import time
from dataclasses import FrozenInstanceError
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.sub_agents._orchestrator_verification import (
    VerificationVerdict,
    _append_verification_block,
    _format_worker_output_for_verifier,
    _parse_verdict,
    _spawn_dict_to_subagent_result,
    run_with_verification,
)
from myrm_agent_harness.agent.sub_agents.types import (
    SubagentConfig,
    SubAgentResult,
    SubAgentStatus,
    VerificationSummary,
)
from myrm_agent_harness.toolkits.code_execution.executors.execution_evidence import record_execution

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok(task_id: str = "t1", agent_type: str = "worker", result: str = "done") -> SubAgentResult:
    return SubAgentResult(
        success=True,
        task_id=task_id,
        agent_type=agent_type,
        result=result,
        completed_at=time.time(),
        status=SubAgentStatus.COMPLETED,
    )


def _fail(task_id: str = "t1", agent_type: str = "worker", error: str = "boom") -> SubAgentResult:
    return SubAgentResult(
        success=False,
        task_id=task_id,
        agent_type=agent_type,
        error=error,
        completed_at=time.time(),
        status=SubAgentStatus.FAILED,
    )


def _verdict_json(
    verdict: str = "PASS",
    summary: str = "ok",
    confidence: str = "HIGH",
    findings: str = "[]",
) -> str:
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
# VerificationSummary
# ---------------------------------------------------------------------------


class TestVerificationSummary:
    def test_frozen_immutability(self):
        s = VerificationSummary(passed=True, rounds=1, max_rounds=2, confidence="HIGH")
        with pytest.raises(FrozenInstanceError):
            s.passed = False  # type: ignore[misc]

    def test_slots(self):
        s = VerificationSummary(passed=True, rounds=1, max_rounds=2, confidence="HIGH")
        assert not hasattr(s, "__dict__")

    def test_to_dict(self):
        s = VerificationSummary(
            passed=True,
            rounds=1,
            max_rounds=2,
            confidence="HIGH",
            summary="All checks passed",
            findings=({"severity": "MINOR", "description": "style"},),
        )
        d = s.to_dict()
        assert d == {
            "passed": True,
            "rounds": 1,
            "max_rounds": 2,
            "confidence": "HIGH",
            "summary": "All checks passed",
            "findings": [{"severity": "MINOR", "description": "style"}],
        }

    def test_subagent_result_round_trip(self):
        summary = VerificationSummary(passed=True, rounds=1, max_rounds=2, confidence="HIGH")
        result = _ok()
        result.verification = summary
        data = result.to_dict()
        assert data["verification"] == summary.to_dict()
        assert data["verification"]["passed"] is True

    def test_subagent_result_without_verification_omits_key(self):
        result = _ok()
        assert "verification" not in result.to_dict()


# ---------------------------------------------------------------------------
# _parse_verdict
# ---------------------------------------------------------------------------


class TestParseVerdict:
    def test_standard_json_pass(self):
        v = _parse_verdict(_verdict_json("PASS", "All good", "HIGH"))
        assert v.passed is True
        assert v.summary == "All good"
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
        raw = "Here is my verdict:\n```json\n" + _verdict_json("PASS", "ok") + "\n```\nEnd."
        v = _parse_verdict(raw)
        assert v.passed is True

    def test_markdown_fenced_without_json_tag(self):
        raw = "```\n" + _verdict_json("FAIL") + "\n```"
        v = _parse_verdict(raw)
        assert v.passed is False

    def test_json_embedded_in_text(self):
        raw = "Based on my analysis, " + _verdict_json("PASS", "Looks good") + " that is my verdict."
        v = _parse_verdict(raw)
        assert v.passed is True
        assert v.summary == "Looks good"

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
        raw = 'After analysis: "verdict": "PASS" — the code is correct.'
        v = _parse_verdict(raw)
        assert v.passed is True
        assert v.confidence == "LOW"
        assert "keyword" in v.summary.lower()

    def test_keyword_fallback_no_space(self):
        raw = 'Result:"verdict":"PASS" end.'
        v = _parse_verdict(raw)
        assert v.passed is True
        assert v.confidence == "LOW"

    def test_keyword_fail_not_triggered(self):
        """FAIL keyword does not have a special fallback — defaults to FAIL anyway."""
        raw = 'The "verdict": "FAIL" because reasons.'
        v = _parse_verdict(raw)
        assert v.passed is False

    def test_verdict_case_insensitive_json(self):
        v = _parse_verdict('{"verdict": "pass", "summary": "ok", "confidence": "HIGH", "findings": []}')
        assert v.passed is True

    def test_verdict_with_extra_fields_ignored(self):
        raw = '{"verdict": "PASS", "summary": "ok", "confidence": "HIGH", "findings": [], "extra_field": 123}'
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
        v = _parse_verdict('  {"verdict": " PASS ", "summary": "ok", "confidence": "HIGH", "findings": []}  ')
        assert v.passed is True

    def test_missing_confidence_defaults_to_unknown(self):
        v = _parse_verdict('{"verdict": "PASS", "summary": "ok", "findings": []}')
        assert v.confidence == "UNKNOWN"

    def test_missing_summary_defaults_to_empty(self):
        v = _parse_verdict('{"verdict": "PASS", "confidence": "HIGH", "findings": []}')
        assert v.summary == ""

    def test_prose_with_trailing_comma_and_bare_newline(self):
        raw = (
            "Verdict after review:\n"
            '{"verdict": "PASS", "summary": "Ran the tool, output matches",'
            ' "confidence": "HIGH", "findings": [],}'
        )
        v = _parse_verdict(raw)
        assert v.passed is True
        assert v.confidence == "HIGH"

    def test_repairable_malformed_json_keeps_its_verdict(self):
        raw = '{"verdict": "PASS", "summary": "ok", "findings": [}'
        v = _parse_verdict(raw)
        assert v.passed is True
        assert v.summary == "ok"

    def test_pass_wording_is_not_second_guessed_by_the_parser(self):
        """Whether a PASS is backed by execution is the verifier round's call, not a parsing heuristic."""
        v = _parse_verdict(_verdict_json("PASS", "looks right to me"))
        assert v.passed is True


class TestVerificationResultShape:
    def test_append_verification_preserves_isolation_dict(self):
        payload = {
            "text": "implemented",
            "_isolated_child_workspace": "/tmp/child",
            "_isolated_parent_workspace": "/tmp/parent",
        }
        updated = _append_verification_block(payload, "[Verification: PASS]")
        assert isinstance(updated, dict)
        assert updated["_isolated_child_workspace"] == "/tmp/child"
        assert updated["_isolated_parent_workspace"] == "/tmp/parent"
        assert "[Verification: PASS]" in updated["_verification_summary"]


# ---------------------------------------------------------------------------
# run_with_verification
# ---------------------------------------------------------------------------


class TestRunWithVerification:
    @pytest.mark.asyncio
    @pytest.mark.usefixtures("verifier_ran_code")
    async def test_pass_on_first_round(self):
        mgr = MagicMock()
        calls: list[str] = []

        async def _spawn(**kwargs):
            calls.append(kwargs["task_id"])
            if "worker" in kwargs["task_id"]:
                return _ok(kwargs["task_id"], kwargs["agent_type"], "work output")
            return _ok(
                kwargs["task_id"],
                kwargs["agent_type"],
                _verdict_json("PASS", "All good", "HIGH"),
            )

        mgr.spawn_child = _spawn
        w_cfg = SubagentConfig(system_prompt="worker")
        v_cfg = SubagentConfig(system_prompt="verifier")

        result = await run_with_verification(
            mgr,
            worker_type="w",
            worker_config=w_cfg,
            worker_task="do work",
            verifier_type="v",
            verifier_config=v_cfg,
            context={},
            tool_registry_getter=lambda: [],
            max_rounds=2,
        )
        assert result.success
        assert "PASS" in result.result
        assert len(calls) == 2  # 1 worker + 1 verifier

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("verifier_ran_code")
    async def test_fail_then_pass_on_retry(self):
        mgr = MagicMock()
        round_counter = {"worker": 0, "verifier": 0}

        async def _spawn(**kwargs):
            if "worker" in kwargs["task_id"]:
                round_counter["worker"] += 1
                return _ok(
                    kwargs["task_id"],
                    kwargs["agent_type"],
                    f"work-r{round_counter['worker']}",
                )
            round_counter["verifier"] += 1
            if round_counter["verifier"] == 1:
                findings = '[{"severity": "MAJOR", "description": "Missing edge case"}]'
                return _ok(
                    kwargs["task_id"],
                    kwargs["agent_type"],
                    _verdict_json("FAIL", "Issues found", "HIGH", findings),
                )
            return _ok(
                kwargs["task_id"],
                kwargs["agent_type"],
                _verdict_json("PASS", "Fixed", "HIGH"),
            )

        mgr.spawn_child = _spawn
        w_cfg = SubagentConfig(system_prompt="worker")
        v_cfg = SubagentConfig(system_prompt="verifier")

        result = await run_with_verification(
            mgr,
            worker_type="w",
            worker_config=w_cfg,
            worker_task="do work",
            verifier_type="v",
            verifier_config=v_cfg,
            context={},
            tool_registry_getter=lambda: [],
            max_rounds=3,
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
            return _ok(
                kwargs["task_id"],
                kwargs["agent_type"],
                _verdict_json("FAIL", "Still broken", "HIGH"),
            )

        mgr.spawn_child = _spawn
        w_cfg = SubagentConfig(system_prompt="worker")
        v_cfg = SubagentConfig(system_prompt="verifier")

        result = await run_with_verification(
            mgr,
            worker_type="w",
            worker_config=w_cfg,
            worker_task="do work",
            verifier_type="v",
            verifier_config=v_cfg,
            context={},
            tool_registry_getter=lambda: [],
            max_rounds=2,
        )
        assert "FAIL after 2 round(s)" in result.result
        assert result.success is False, "Verification failure must propagate success=False"
        assert result.verification is not None
        assert result.verification.passed is False
        assert result.verification.max_rounds == 2
        assert result.verification.confidence == "HIGH"
        assert result.verification.summary == "Still broken"

    @pytest.mark.asyncio
    async def test_worker_failure_aborts(self):
        mgr = MagicMock()

        async def _spawn(**kwargs):
            return _fail(kwargs["task_id"], kwargs["agent_type"], "worker crashed")

        mgr.spawn_child = _spawn
        w_cfg = SubagentConfig(system_prompt="worker")
        v_cfg = SubagentConfig(system_prompt="verifier")

        result = await run_with_verification(
            mgr,
            worker_type="w",
            worker_config=w_cfg,
            worker_task="do work",
            verifier_type="v",
            verifier_config=v_cfg,
            context={},
            tool_registry_getter=lambda: [],
        )
        assert not result.success
        assert "worker crashed" in result.error
        assert result.verification is None, "Worker failure must not fabricate a verification outcome"
        assert "Verification:" not in (result.result or "")

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("verifier_ran_code")
    async def test_rework_worker_failure_is_not_reported_as_a_verification_fail(self):
        mgr = MagicMock()
        worker_calls = 0

        async def _spawn(**kwargs):
            nonlocal worker_calls
            if "worker" in kwargs["task_id"]:
                worker_calls += 1
                if worker_calls == 1:
                    return _ok(kwargs["task_id"], kwargs["agent_type"], "first attempt")
                return _fail(kwargs["task_id"], kwargs["agent_type"], "rework crashed")
            return _ok(
                kwargs["task_id"],
                kwargs["agent_type"],
                _verdict_json("FAIL", "round one found a defect", "HIGH"),
            )

        mgr.spawn_child = _spawn

        result = await run_with_verification(
            mgr,
            worker_type="w",
            worker_config=SubagentConfig(system_prompt="worker"),
            worker_task="do work",
            verifier_type="v",
            verifier_config=SubagentConfig(system_prompt="verifier"),
            context={},
            tool_registry_getter=lambda: [],
            max_rounds=2,
        )

        assert not result.success
        assert result.error == "rework crashed"
        assert result.verification is None, "Round one's verdict judged another output and must not be reported"
        assert "Verification:" not in (result.result or "")

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
            mgr,
            worker_type="w",
            worker_config=w_cfg,
            worker_task="do work",
            verifier_type="v",
            verifier_config=v_cfg,
            context={},
            tool_registry_getter=lambda: [],
        )
        assert result.status == SubAgentStatus.BLOCKED
        assert result.verification is None
        assert "Verification: INCOMPLETE" in result.result
        assert "FAIL" not in result.result
        assert call_count == 2, "An inconclusive verifier must not trigger worker rework"

    @pytest.mark.asyncio
    async def test_max_rounds_clamped_to_one(self):
        mgr = MagicMock()

        async def _spawn(**kwargs):
            if "worker" in kwargs["task_id"]:
                return _ok(kwargs["task_id"], kwargs["agent_type"], "work")
            return _ok(
                kwargs["task_id"],
                kwargs["agent_type"],
                _verdict_json("FAIL", "fail", "HIGH"),
            )

        mgr.spawn_child = _spawn
        w_cfg = SubagentConfig(system_prompt="worker")
        v_cfg = SubagentConfig(system_prompt="verifier")

        result = await run_with_verification(
            mgr,
            worker_type="w",
            worker_config=w_cfg,
            worker_task="do work",
            verifier_type="v",
            verifier_config=v_cfg,
            context={},
            tool_registry_getter=lambda: [],
            max_rounds=0,
        )
        assert "FAIL after 1 round(s)" in result.result

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("verifier_ran_code")
    async def test_custom_verifier_task_template(self):
        mgr = MagicMock()
        captured_desc: list[str] = []

        async def _spawn(**kwargs):
            captured_desc.append(kwargs["task_description"])
            if "worker" in kwargs["task_id"]:
                return _ok(kwargs["task_id"], kwargs["agent_type"], "my-output")
            return _ok(kwargs["task_id"], kwargs["agent_type"], _verdict_json("PASS"))

        mgr.spawn_child = _spawn
        w_cfg = SubagentConfig(system_prompt="worker")
        v_cfg = SubagentConfig(system_prompt="verifier")

        await run_with_verification(
            mgr,
            worker_type="w",
            worker_config=w_cfg,
            worker_task="do work",
            verifier_type="v",
            verifier_config=v_cfg,
            context={},
            tool_registry_getter=lambda: [],
            verifier_task_template="CHECK THIS: {worker_result}",
        )
        assert "CHECK THIS: my-output" in captured_desc[1]

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("verifier_ran_code")
    async def test_retry_feedback_contains_findings(self):
        mgr = MagicMock()
        worker_tasks: list[str] = []

        async def _spawn(**kwargs):
            if "worker" in kwargs["task_id"]:
                worker_tasks.append(kwargs["task_description"])
                return _ok(kwargs["task_id"], kwargs["agent_type"], "work")
            if len(worker_tasks) == 1:
                return _ok(
                    kwargs["task_id"],
                    kwargs["agent_type"],
                    _verdict_json(
                        "FAIL",
                        "bug",
                        "HIGH",
                        '[{"severity": "CRITICAL", "description": "null check missing"}]',
                    ),
                )
            return _ok(kwargs["task_id"], kwargs["agent_type"], _verdict_json("PASS"))

        mgr.spawn_child = _spawn
        w_cfg = SubagentConfig(system_prompt="worker")
        v_cfg = SubagentConfig(system_prompt="verifier")

        await run_with_verification(
            mgr,
            worker_type="w",
            worker_config=w_cfg,
            worker_task="original task",
            verifier_type="v",
            verifier_config=v_cfg,
            context={},
            tool_registry_getter=lambda: [],
            max_rounds=3,
        )
        assert len(worker_tasks) >= 2
        assert "null check missing" in worker_tasks[1]
        assert "original task" in worker_tasks[1]

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("verifier_ran_code")
    async def test_dict_return_from_spawn_child(self):
        mgr = MagicMock()

        async def _spawn(**kwargs):
            if "worker" in kwargs["task_id"]:
                return {"success": True, "result": "dict-output"}
            return {"success": True, "result": _verdict_json("PASS")}

        mgr.spawn_child = _spawn
        w_cfg = SubagentConfig(system_prompt="worker")
        v_cfg = SubagentConfig(system_prompt="verifier")

        result = await run_with_verification(
            mgr,
            worker_type="w",
            worker_config=w_cfg,
            worker_task="do work",
            verifier_type="v",
            verifier_config=v_cfg,
            context={},
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
            mgr,
            worker_type="w",
            worker_config=w_cfg,
            worker_task="do work",
            verifier_type="v",
            verifier_config=v_cfg,
            context={},
            tool_registry_getter=lambda: [],
        )
        assert not result.success

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("verifier_ran_code")
    async def test_verification_metadata_in_pass_result(self):
        mgr = MagicMock()

        async def _spawn(**kwargs):
            if "worker" in kwargs["task_id"]:
                return _ok(kwargs["task_id"], kwargs["agent_type"], "done")
            return _ok(
                kwargs["task_id"],
                kwargs["agent_type"],
                _verdict_json("PASS", "ok", "MEDIUM"),
            )

        mgr.spawn_child = _spawn
        w_cfg = SubagentConfig(system_prompt="worker")
        v_cfg = SubagentConfig(system_prompt="verifier")

        result = await run_with_verification(
            mgr,
            worker_type="w",
            worker_config=w_cfg,
            worker_task="do work",
            verifier_type="v",
            verifier_config=v_cfg,
            context={},
            tool_registry_getter=lambda: [],
        )
        assert "Verification: PASS" in result.result
        assert "round 1/2" in result.result
        assert "confidence=MEDIUM" in result.result
        assert result.verification is not None
        assert result.verification.passed is True
        assert result.verification.rounds == 1
        assert result.verification.max_rounds == 2
        assert result.verification.confidence == "MEDIUM"
        assert result.verification.summary == "ok"

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("verifier_ran_code")
    async def test_tool_call_verdict_used_when_present(self):
        """When verifier sets _verifier_verdict via tool call, it takes precedence over text parsing."""
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
            mgr,
            worker_type="w",
            worker_config=w_cfg,
            worker_task="do work",
            verifier_type="v",
            verifier_config=v_cfg,
            context={},
            tool_registry_getter=lambda: [],
            max_rounds=2,
        )
        assert result.success
        assert "PASS" in result.result

    @pytest.mark.asyncio
    async def test_pass_without_execution_is_inconclusive_not_a_failed_verification(self):
        """A PASS nobody ran anything for leaves the output unverified, and the worker is not sent into rework."""
        mgr = MagicMock()
        worker_runs = 0

        async def _spawn(**kwargs):
            nonlocal worker_runs
            if "worker" in kwargs["task_id"]:
                worker_runs += 1
                return _ok(kwargs["task_id"], kwargs["agent_type"], "work done")
            return _ok(
                kwargs["task_id"],
                kwargs["agent_type"],
                _verdict_json("PASS", "Looks good", "HIGH"),
            )

        mgr.spawn_child = _spawn
        w_cfg = SubagentConfig(system_prompt="worker")
        v_cfg = SubagentConfig(system_prompt="verifier")

        result = await run_with_verification(
            mgr,
            worker_type="w",
            worker_config=w_cfg,
            worker_task="do work",
            verifier_type="v",
            verifier_config=v_cfg,
            context={},
            tool_registry_getter=lambda: [],
            max_rounds=3,
        )
        assert not result.success
        assert result.status == SubAgentStatus.BLOCKED
        assert result.error == "Verifier produced no conclusive verdict"
        assert result.verification is None
        assert "Verification: INCOMPLETE" in result.result
        assert "did not execute any code" not in result.result
        assert worker_runs == 1

    @pytest.mark.asyncio
    async def test_verification_metadata_in_fail_result(self):
        mgr = MagicMock()

        async def _spawn(**kwargs):
            if "worker" in kwargs["task_id"]:
                return _ok(kwargs["task_id"], kwargs["agent_type"], "work")
            return _ok(
                kwargs["task_id"],
                kwargs["agent_type"],
                _verdict_json("FAIL", "bad", "HIGH"),
            )

        mgr.spawn_child = _spawn
        w_cfg = SubagentConfig(system_prompt="worker")
        v_cfg = SubagentConfig(system_prompt="verifier")

        result = await run_with_verification(
            mgr,
            worker_type="w",
            worker_config=w_cfg,
            worker_task="do work",
            verifier_type="v",
            verifier_config=v_cfg,
            context={},
            tool_registry_getter=lambda: [],
            max_rounds=1,
        )
        assert "Verification: FAIL after 1 round(s)" in result.result
        assert result.success is False, "Verification failure must set success=False"

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("verifier_ran_code")
    async def test_business_task_id_first_worker_visible_retries_internal(self):
        """With a business task_id, the first worker runs under that id (visible),
        while retry workers and verifiers spawn as internal nodes."""
        mgr = MagicMock()
        spawned: list[tuple[str, bool]] = []

        async def _spawn(**kwargs):
            spawned.append((kwargs["task_id"], kwargs.get("internal", False)))
            tid = kwargs["task_id"]
            if "worker" in tid:
                return _ok(tid, kwargs["agent_type"], "work output")
            if len(spawned) == 2:
                return _ok(
                    tid,
                    kwargs["agent_type"],
                    _verdict_json("FAIL", "Issues found", "HIGH"),
                )
            return _ok(tid, kwargs["agent_type"], _verdict_json("PASS", "ok", "HIGH"))

        mgr.spawn_child = _spawn
        w_cfg = SubagentConfig(system_prompt="worker")
        v_cfg = SubagentConfig(system_prompt="verifier")

        result = await run_with_verification(
            mgr,
            worker_type="w",
            worker_config=w_cfg,
            worker_task="do work",
            verifier_type="v",
            verifier_config=v_cfg,
            context={},
            tool_registry_getter=lambda: [],
            max_rounds=3,
            task_id="biz-1234",
        )
        assert result.success
        assert result.task_id == "biz-1234"
        assert result.internal is False

        assert spawned[0] == (
            "biz-1234",
            False,
        ), "first worker reuses business id, visible"
        # Round 1 verifier, round 2 worker, round 2 verifier are all internal
        assert all(internal for _, internal in spawned[1:]), spawned

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("verifier_ran_code")
    async def test_pass_first_round_keeps_business_task_id(self):
        """PASS on the first round returns the business node with its id intact."""
        mgr = MagicMock()

        async def _spawn(**kwargs):
            tid = kwargs["task_id"]
            if "worker" in tid:
                return _ok(tid, kwargs["agent_type"], "work output")
            return _ok(tid, kwargs["agent_type"], _verdict_json("PASS", "ok", "HIGH"))

        mgr.spawn_child = _spawn
        w_cfg = SubagentConfig(system_prompt="worker")
        v_cfg = SubagentConfig(system_prompt="verifier")

        result = await run_with_verification(
            mgr,
            worker_type="w",
            worker_config=w_cfg,
            worker_task="do work",
            verifier_type="v",
            verifier_config=v_cfg,
            context={},
            tool_registry_getter=lambda: [],
            max_rounds=2,
            task_id="biz-5678",
        )
        assert result.success
        assert result.task_id == "biz-5678"
        assert result.internal is False
        assert result.verification is not None
        assert result.verification.passed is True

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("verifier_ran_code")
    async def test_no_task_id_keeps_internal_worker_ids(self):
        """Without a business task_id, every spawned worker is internal."""
        mgr = MagicMock()
        spawned: list[tuple[str, bool]] = []

        async def _spawn(**kwargs):
            spawned.append((kwargs["task_id"], kwargs.get("internal", False)))
            tid = kwargs["task_id"]
            if "worker" in tid:
                return _ok(tid, kwargs["agent_type"], "work output")
            return _ok(tid, kwargs["agent_type"], _verdict_json("PASS", "ok", "HIGH"))

        mgr.spawn_child = _spawn
        w_cfg = SubagentConfig(system_prompt="worker")
        v_cfg = SubagentConfig(system_prompt="verifier")

        result = await run_with_verification(
            mgr,
            worker_type="w",
            worker_config=w_cfg,
            worker_task="do work",
            verifier_type="v",
            verifier_config=v_cfg,
            context={},
            tool_registry_getter=lambda: [],
            max_rounds=2,
        )
        assert result.success
        assert all(internal for _, internal in spawned), spawned


class TestVerifyWorkerOutput:
    @pytest.mark.asyncio
    async def test_returns_no_verdict_when_verifier_subagent_fails(self):
        from myrm_agent_harness.agent.sub_agents._verifier_round import (
            verify_worker_output,
        )

        mgr = MagicMock()

        async def _spawn(**kwargs):
            return _fail(kwargs["task_id"], kwargs["agent_type"], "verifier crashed")

        mgr.spawn_child = _spawn
        v_cfg = SubagentConfig(system_prompt="verifier")

        verdict = await verify_worker_output(
            mgr,
            worker_output="worker output",
            worker_type="worker",
            verifier_type="adversarial-reviewer",
            verifier_config=v_cfg,
            context={},
            tool_registry_getter=lambda: [],
        )
        assert verdict is None


class TestSubAgentResultInternal:
    def test_internal_defaults_false(self):
        r = SubAgentResult(success=True, task_id="t1", agent_type="w")
        assert r.internal is False

    def test_internal_excluded_from_to_dict_when_false(self):
        r = SubAgentResult(success=True, task_id="t1", agent_type="w")
        assert "internal" not in r.to_dict()

    def test_internal_serialized_when_true(self):
        r = SubAgentResult(
            success=True,
            task_id="t1",
            agent_type="w",
            completed_at=100.0,
            internal=True,
        )
        d = r.to_dict()
        assert d["internal"] is True

    def test_verifier_result_dict_marks_internal(self):
        """dict-shaped spawn results from internal verifiers keep the flag."""
        from myrm_agent_harness.agent.sub_agents._orchestrator_verification import (
            _spawn_dict_to_subagent_result,
        )

        r = _spawn_dict_to_subagent_result(
            {"success": True, "result": "out", "error": ""},
            task_id="verify-check-1-v",
            agent_type="v",
        )
        assert r.internal is False  # conversion itself is neutral
        r.internal = True  # set by callers after conversion
        assert r.to_dict()["internal"] is True


class TestSyncBusinessResultFields:
    """Guards the dynamic field mirroring in _sync_business_result.

    The sync field set is derived from the SubAgentResult dataclass so future
    fields are mirrored automatically. These tests pin the contract: exactly
    the non-managed dataclass fields are copied, identity fields are not.
    """

    def test_sync_fields_cover_all_non_managed_dataclass_fields(self):
        from dataclasses import fields as dc_fields

        from myrm_agent_harness.agent.sub_agents._orchestrator_verification import (
            _SYNC_FIELDS,
        )

        managed = {"task_id", "agent_type", "internal"}
        all_fields = {f.name for f in dc_fields(SubAgentResult)}
        assert set(_SYNC_FIELDS) == all_fields - managed

    def test_sync_business_result_mirrors_only_sync_fields(self):
        from myrm_agent_harness.agent.sub_agents._orchestrator_verification import (
            _sync_business_result,
        )

        source = SubAgentResult(
            success=True,
            task_id="verify-worker-2-w",
            agent_type="w",
            result="final result",
            error="",
            completed_at=200.0,
            status=SubAgentStatus.COMPLETED,
            internal=True,
            verification=VerificationSummary(
                passed=True,
                rounds=2,
                max_rounds=2,
                confidence="HIGH",
                summary="verified",
            ),
        )
        business = SubAgentResult(
            success=False,
            task_id="biz-id",
            agent_type="original-agent",
            result="stale",
            completed_at=0.0,
            status=SubAgentStatus.FAILED,
        )

        _sync_business_result(business, source, "biz-id")

        assert business.success is True
        assert business.result == "final result"
        assert business.status is SubAgentStatus.COMPLETED
        assert business.completed_at == 200.0
        assert business.verification is not None
        assert business.verification.passed is True
        # Identity fields are pinned by the caller, not copied from the source.
        assert business.task_id == "biz-id"
        assert business.agent_type == "original-agent"
        assert business.internal is False

    def test_sync_business_result_noop_when_source_is_business(self):
        from myrm_agent_harness.agent.sub_agents._orchestrator_verification import (
            _sync_business_result,
        )

        business = _ok("biz-id")
        _sync_business_result(business, business, "biz-id")
        assert business.result == "done"


class TestInternalIdUniqueness:
    """Guards the uniqueness of framework-generated internal task ids.

    Parallel delegated tasks share the same SubagentManager: fixed-format
    internal ids (``verify-worker-N-*`` / ``verify-check-N-*``) would collide in
    ``_task_id_exists`` and the second delegate's verification would fail.
    """

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("verifier_ran_code")
    async def test_parallel_invokes_spawn_unique_internal_ids(self):
        mgr = MagicMock()
        spawned: list[str] = []

        async def _spawn(**kwargs):
            spawned.append(kwargs["task_id"])
            if kwargs["agent_type"] == "w":
                return _ok(kwargs["task_id"], "w", "work output")
            return _ok(kwargs["task_id"], "v", _verdict_json("PASS", "ok", "HIGH"))

        mgr.spawn_child = _spawn
        w_cfg = SubagentConfig(system_prompt="worker")
        v_cfg = SubagentConfig(system_prompt="verifier")

        for i in range(2):
            result = await run_with_verification(
                mgr,
                worker_type="w",
                worker_config=w_cfg,
                worker_task="do work",
                verifier_type="v",
                verifier_config=v_cfg,
                context={},
                tool_registry_getter=lambda: [],
                max_rounds=2,
                task_id=f"biz-{i}",
            )
            assert result.success

        internal_ids = [tid for tid in spawned if tid.startswith(("verify-worker-", "verify-check-"))]
        assert len(internal_ids) == 2  # one verifier per invocation
        assert len(internal_ids) == len(set(internal_ids)), internal_ids


# ---------------------------------------------------------------------------
# Rendering / dict helpers
# ---------------------------------------------------------------------------


class TestFormatWorkerOutput:
    def test_dict_with_text_returns_text(self):
        assert _format_worker_output_for_verifier({"text": "hello", "other": 1}) == "hello"

    def test_dict_without_text_returns_filtered_json(self):
        result = _format_worker_output_for_verifier(
            {"a": 1, "_workspace_sync_back": "x", "_isolated_child_workspace": "y"}
        )
        assert '"a": 1' in result
        assert "_workspace_sync_back" not in result
        assert "_isolated_child_workspace" not in result

    def test_dict_all_filtered_falls_back_to_str(self):
        result = _format_worker_output_for_verifier({"_verification_summary": "s"})
        assert "s" in result

    def test_non_dict_returns_str(self):
        assert _format_worker_output_for_verifier("plain") == "plain"


class TestAppendVerificationBlock:
    def test_dict_with_prior_summary_appends(self):
        updated = _append_verification_block({"result": "r", "_verification_summary": "old"}, "block")
        assert updated["_verification_summary"] == "old\n\nblock"

    def test_dict_without_prior_sets_summary_and_append_text(self):
        updated = _append_verification_block({"result": "r", "text": "t"}, "block")
        assert updated["_verification_summary"] == "block"
        assert updated["text"] == "t\n\nblock"

    def test_non_dict_appends_as_string(self):
        assert _append_verification_block("plain", "block") == "plain\n\nblock"


class TestSpawnDictToSubagentResult:
    def test_non_text_result_coerced_to_str(self):
        result = _spawn_dict_to_subagent_result(
            {"result": 123, "success": True},
            task_id="t1",
            agent_type="worker",
        )
        assert result.result == "123"
        assert result.success
        assert result.task_id == "t1"
        assert result.agent_type == "worker"


# ---------------------------------------------------------------------------
# Verifier tool registry filtering
# ---------------------------------------------------------------------------


class TestBuildVerifierToolRegistryGetter:
    def test_passes_parent_tools_through_and_appends_verdict_tool(self):
        from myrm_agent_harness.agent.sub_agents._verifier_round import (
            _build_verifier_tool_registry_getter,
        )

        parent_tools = [MagicMock(), MagicMock()]

        tools = _build_verifier_tool_registry_getter(lambda: parent_tools, {})()

        assert tools[:2] == parent_tools
        assert [getattr(t, "name", "") for t in tools[2:]] == ["submit_verdict"]


# ---------------------------------------------------------------------------
# Early cancellation
# ---------------------------------------------------------------------------


class TestRunWithVerificationCancelled:
    @pytest.mark.asyncio
    async def test_cancel_before_first_round(self):
        cancel_token = MagicMock()
        cancel_token.is_cancelled = True
        mgr = MagicMock()
        mgr.spawn_child = AsyncMock()
        w_cfg = SubagentConfig(system_prompt="worker")
        v_cfg = SubagentConfig(system_prompt="verifier")

        result = await run_with_verification(
            mgr,
            worker_type="w",
            worker_config=w_cfg,
            worker_task="do work",
            verifier_type="v",
            verifier_config=v_cfg,
            context={},
            tool_registry_getter=lambda: [],
            cancel_token=cancel_token,
        )
        assert result.error == "Cancelled"
        assert not result.success
        mgr.spawn_child.assert_not_awaited()


class TestExecuteVerifierRoundWorkspaceDiff:
    @pytest.mark.asyncio
    @patch("myrm_agent_harness.agent.sub_agents._verifier_round.diff_snapshots")
    @patch("myrm_agent_harness.agent.sub_agents._verifier_round.take_workspace_snapshot")
    @pytest.mark.usefixtures("verifier_ran_code")
    async def test_diff_injected_and_verdict_returned(self, mock_snapshot, mock_diff):
        from myrm_agent_harness.agent.sub_agents._verifier_round import (
            _execute_verifier_round,
        )

        mock_snapshot.return_value = {"file.py": (10.0, 5)}
        mock_diff.return_value = "--- /dev/null\n+++ b/file.py\n"

        mgr = MagicMock()

        async def _spawn(**kwargs):
            assert kwargs["internal"] is True
            return _ok(
                kwargs["task_id"],
                kwargs["agent_type"],
                _verdict_json("PASS", "ok", "HIGH"),
            )

        mgr.spawn_child = _spawn
        cfg = SubagentConfig(system_prompt="verifier")

        verdict = await _execute_verifier_round(
            mgr,
            worker_output="work output",
            worker_type="w",
            verifier_type="v",
            verifier_config=cfg,
            context={"workspace_path": "/tmp/w"},
            tool_registry_getter=lambda: [],
            round_num=1,
            max_rounds=2,
            verifier_task_template="Check the file list.",
            pre_snapshot={"file.py": (0.0, 0)},
        )

        assert verdict is not None
        assert verdict.passed
        assert mock_snapshot.called
        assert mock_diff.called


class TestRunWithVerificationSnapshotFailure:
    @pytest.mark.asyncio
    @patch("myrm_agent_harness.agent.sub_agents._orchestrator_verification.take_workspace_snapshot")
    @pytest.mark.usefixtures("verifier_ran_code")
    async def test_pre_snapshot_failure_does_not_abort(self, mock_snapshot):
        mock_snapshot.side_effect = OSError("snapshot failed")
        mgr = MagicMock()

        async def _spawn(**kwargs):
            if "worker" in kwargs["task_id"]:
                return _ok(kwargs["task_id"], kwargs["agent_type"], "work")
            return _ok(
                kwargs["task_id"],
                kwargs["agent_type"],
                _verdict_json("PASS", "All good", "HIGH"),
            )

        mgr.spawn_child = _spawn
        w_cfg = SubagentConfig(system_prompt="worker")
        v_cfg = SubagentConfig(system_prompt="verifier")

        result = await run_with_verification(
            mgr,
            worker_type="w",
            worker_config=w_cfg,
            worker_task="do work",
            verifier_type="v",
            verifier_config=v_cfg,
            context={"workspace_path": "/tmp/nonexistent-dir"},
            tool_registry_getter=lambda: [],
            max_rounds=2,
        )
        assert result.success


# ---------------------------------------------------------------------------
# Auditor Blind & Snapshot Mutation Revert Tests
# ---------------------------------------------------------------------------


class TestAuditorBlindAndSnapshotRevert:
    @pytest.mark.asyncio
    @patch("myrm_agent_harness.agent.sub_agents._verifier_round.diff_snapshots")
    @patch("myrm_agent_harness.agent.sub_agents._verifier_round.take_workspace_snapshot")
    @patch("myrm_agent_harness.agent.sub_agents._verifier_round.revert_workspace_mutations")
    @pytest.mark.usefixtures("verifier_ran_code")
    async def test_auditor_blind_omits_worker_narrative_when_diff_present(self, mock_revert, mock_snapshot, mock_diff):
        from myrm_agent_harness.agent.sub_agents._verifier_round import (
            _execute_verifier_round,
        )

        mock_snapshot.return_value = {"file.py": (10.0, 5)}
        mock_diff.return_value = "## Workspace Changes\n- `file.py` modified"
        mock_revert.return_value = []

        spawned_desc = []
        mgr = MagicMock()

        async def _spawn(**kwargs):
            spawned_desc.append(kwargs["task_description"])
            return _ok(
                kwargs["task_id"],
                kwargs["agent_type"],
                _verdict_json("PASS", "Blind check ok", "HIGH"),
            )

        mgr.spawn_child = _spawn
        cfg = SubagentConfig(system_prompt="verifier")

        verdict = await _execute_verifier_round(
            mgr,
            worker_output="I am the best worker and I fixed all bugs perfectly!",
            worker_type="w",
            verifier_type="v",
            verifier_config=cfg,
            context={"workspace_path": "/tmp/w"},
            tool_registry_getter=lambda: [],
            round_num=1,
            max_rounds=1,
            pre_snapshot={"file.py": (0.0, 0)},
            auditor_blind=True,
        )

        assert verdict is not None
        assert verdict.passed
        assert len(spawned_desc) == 1
        # Worker subjective narrative must be stripped in auditor_blind mode
        assert "I am the best worker" not in spawned_desc[0]
        assert "Auditor Blind" in spawned_desc[0]
        assert mock_revert.called

    def test_revert_workspace_mutations_deletes_added_files(self, tmp_path):
        from myrm_agent_harness.agent.sub_agents._workspace_diff import (
            revert_workspace_mutations,
        )

        base_file = tmp_path / "base.py"
        base_file.write_text("print('base')")

        pre_snapshot = {"base.py": (base_file.stat().st_mtime, base_file.stat().st_size)}

        # Verifier created stray test files
        stray_file = tmp_path / "test_temp_out.py"
        stray_file.write_text("print('stray')")

        post_snapshot = {
            "base.py": (base_file.stat().st_mtime, base_file.stat().st_size),
            "test_temp_out.py": (stray_file.stat().st_mtime, stray_file.stat().st_size),
        }

        reverted = revert_workspace_mutations(tmp_path, pre_snapshot, post_snapshot)
        assert "test_temp_out.py" in reverted
        assert not stray_file.exists()
        assert base_file.exists()


# ---------------------------------------------------------------------------
# Multi-Skeptic Voting & Fail-Closed Tests
# ---------------------------------------------------------------------------


class TestMultiSkepticVerification:
    @pytest.mark.asyncio
    @patch("myrm_agent_harness.agent.sub_agents._orchestrator_verification.take_workspace_snapshot")
    @pytest.mark.usefixtures("verifier_ran_code")
    async def test_multi_skeptic_majority_pass(self, mock_snapshot):
        mock_snapshot.return_value = {"file.py": (10.0, 5)}

        mgr = MagicMock()
        call_count = 0

        async def _spawn(**kwargs):
            nonlocal call_count
            task_id = kwargs["task_id"]
            if "worker" in task_id or task_id == "biz-task":
                return _ok(task_id, "worker", "worker done")
            call_count += 1
            # 2 Pass, 1 Fail -> Majority PASS
            verdict_str = "PASS" if call_count <= 2 else "FAIL"
            return _ok(
                task_id,
                "verifier",
                _verdict_json(verdict_str, f"Skeptic {call_count}", "HIGH"),
            )

        mgr.spawn_child = _spawn
        w_cfg = SubagentConfig(system_prompt="worker")
        v_cfg = SubagentConfig(system_prompt="verifier")

        result = await run_with_verification(
            mgr,
            worker_type="worker",
            worker_config=w_cfg,
            worker_task="do task",
            verifier_type="verifier",
            verifier_config=v_cfg,
            context={"workspace_path": "/tmp/w"},
            tool_registry_getter=lambda: [],
            max_rounds=1,
            task_id="biz-task",
            verification_mode="multi_skeptic",
        )

        assert result.success
        assert result.verification is not None
        assert result.verification.passed is True
        assert "Multi-Skeptic Voting: 2/3 approved (majority=PASS)" in result.verification.summary

    @pytest.mark.asyncio
    @patch("myrm_agent_harness.agent.sub_agents._orchestrator_verification.take_workspace_snapshot")
    @pytest.mark.parametrize(
        ("skeptic_plan", "expected_passed", "expected_tally"),
        [
            ([("PASS", False), ("PASS", True), ("PASS", True)], True, "2/2 approved"),
            ([("PASS", False), ("PASS", True), ("FAIL", True)], False, "1/2 approved"),
            ([("FAIL", True), ("PASS", False), ("PASS", False)], False, "0/1 approved"),
        ],
    )
    async def test_multi_skeptic_lazy_skeptic_abstains_instead_of_voting(
        self, mock_snapshot, skeptic_plan, expected_passed, expected_tally
    ):
        """A skeptic that passed without launching any command casts no vote, in either direction."""
        mock_snapshot.return_value = {}

        mgr = MagicMock()
        skeptic_calls = 0

        async def _spawn(**kwargs):
            nonlocal skeptic_calls
            task_id = kwargs["task_id"]
            if "worker" in task_id or task_id == "biz-task":
                return _ok(task_id, "worker", "worker done")
            verdict_str, ran_command = skeptic_plan[skeptic_calls]
            skeptic_calls += 1
            if ran_command:
                record_execution()
            return _ok(task_id, "verifier", _verdict_json(verdict_str, f"Skeptic {skeptic_calls}", "HIGH"))

        mgr.spawn_child = _spawn

        result = await run_with_verification(
            mgr,
            worker_type="worker",
            worker_config=SubagentConfig(system_prompt="worker"),
            worker_task="do task",
            verifier_type="verifier",
            verifier_config=SubagentConfig(system_prompt="verifier"),
            context={"workspace_path": "/tmp/w"},
            tool_registry_getter=lambda: [],
            max_rounds=1,
            task_id="biz-task",
            verification_mode="multi_skeptic",
        )

        assert result.verification is not None
        assert result.verification.passed is expected_passed
        assert expected_tally in result.verification.summary

    @pytest.mark.asyncio
    @patch("myrm_agent_harness.agent.sub_agents._orchestrator_verification.take_workspace_snapshot")
    @pytest.mark.parametrize(
        "ran_command_per_skeptic",
        [
            [False, False, False],
            [True, False, False],
        ],
    )
    async def test_multi_skeptic_without_a_deciding_vote_blocks_without_a_verdict(
        self, mock_snapshot, ran_command_per_skeptic
    ):
        """No conclusive vote, or a lone PASS that can neither reach the quorum nor prove a defect, decides nothing."""
        mock_snapshot.return_value = {}

        mgr = MagicMock()
        skeptic_calls = 0

        async def _spawn(**kwargs):
            nonlocal skeptic_calls
            task_id = kwargs["task_id"]
            if "worker" in task_id or task_id == "biz-task":
                return _ok(task_id, "worker", "worker done")
            if ran_command_per_skeptic[skeptic_calls]:
                record_execution()
            skeptic_calls += 1
            return _ok(task_id, "verifier", _verdict_json("PASS", "Skeptic"))

        mgr.spawn_child = _spawn

        result = await run_with_verification(
            mgr,
            worker_type="worker",
            worker_config=SubagentConfig(system_prompt="worker"),
            worker_task="do task",
            verifier_type="verifier",
            verifier_config=SubagentConfig(system_prompt="verifier"),
            context={"workspace_path": "/tmp/w"},
            tool_registry_getter=lambda: [],
            max_rounds=1,
            task_id="biz-task",
            verification_mode="multi_skeptic",
        )

        assert result.status == SubAgentStatus.BLOCKED
        assert result.verification is None
        assert result.error == "Multi-skeptic verifiers produced no conclusive verdict (Fail-Closed blocked)."

    @pytest.mark.asyncio
    @patch("myrm_agent_harness.agent.sub_agents._orchestrator_verification.take_workspace_snapshot")
    @pytest.mark.usefixtures("verifier_ran_code")
    async def test_multi_skeptic_fail_closed_on_crash(self, mock_snapshot):
        mock_snapshot.return_value = {}

        mgr = MagicMock()

        async def _spawn(**kwargs):
            task_id = kwargs["task_id"]
            if "worker" in task_id:
                return _ok(task_id, "worker", "worker done")
            raise RuntimeError("Fatal verifier sandboxing crash")

        mgr.spawn_child = _spawn
        w_cfg = SubagentConfig(system_prompt="worker")
        v_cfg = SubagentConfig(system_prompt="verifier")

        result = await run_with_verification(
            mgr,
            worker_type="worker",
            worker_config=w_cfg,
            worker_task="do task",
            verifier_type="verifier",
            verifier_config=v_cfg,
            context={"workspace_path": "/tmp/w"},
            tool_registry_getter=lambda: [],
            max_rounds=1,
            verification_mode="multi_skeptic",
        )

        assert not result.success
        assert result.status == SubAgentStatus.BLOCKED
        assert "Fail-Closed blocked" in result.error
