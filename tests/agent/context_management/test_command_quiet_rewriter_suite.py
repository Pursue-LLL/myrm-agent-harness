"""Unit tests for Command Output Preflight Quiet Rewriter and Subagent Log Sink Suite.

Verifies preflight command quiet flag injection, verbose bypass preservation,
subagent log sink blackhole isolation, noise reduction ratio >= 90%, and facade integration.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management import (
    CommandQuietRewriterAndLogSinkSuite,
    LogSinkConclusionCard,
    LogSinkStatus,
    LogSinkTaskSpec,
    LogSinkTaskType,
    PreflightCommandRewriter,
    RewriteStatus,
    SubagentLogSinkEngine,
)


def test_preflight_command_rewriter_rules_and_bypass() -> None:
    """Verify preflight command rewriting across pytest, vitest, npm, git log, curl."""
    rewriter = PreflightCommandRewriter()

    # 1. pytest rewrite
    res1 = rewriter.rewrite("pytest tests/agent/")
    assert res1.status == RewriteStatus.REWRITTEN
    assert res1.rewritten_command == "pytest tests/agent/ -q --tb=short"
    assert res1.was_modified is True

    # 2. python -m pytest
    res2 = rewriter.rewrite("python -m pytest tests/")
    assert res2.status == RewriteStatus.REWRITTEN
    assert res2.rewritten_command == "python -m pytest tests/ -q --tb=short"

    # 3. vitest rewrite
    res3 = rewriter.rewrite("vitest run")
    assert res3.status == RewriteStatus.REWRITTEN
    assert "--reporter=dot" in res3.rewritten_command
    assert "--silent" in res3.rewritten_command

    # 4. npm install rewrite
    res4 = rewriter.rewrite("npm install express")
    assert res4.status == RewriteStatus.REWRITTEN
    assert res4.rewritten_command == "npm install express --silent"

    # 5. git log rewrite
    res5 = rewriter.rewrite("git log")
    assert res5.status == RewriteStatus.REWRITTEN
    assert res5.rewritten_command == "git log --oneline -n 20"

    # 6. git log already bounded
    res6 = rewriter.rewrite("git log -5")
    assert res6.status == RewriteStatus.UNCHANGED
    assert res6.rewritten_command == "git log -5"

    # 7. curl rewrite
    res7 = rewriter.rewrite("curl https://api.openai.com/v1/models")
    assert res7.status == RewriteStatus.REWRITTEN
    assert "-s -S" in res7.rewritten_command

    # 8. Explicit verbose flag must bypass rewriting to preserve debugging intent
    res_verb = rewriter.rewrite("pytest -v tests/")
    assert res_verb.status == RewriteStatus.BYPASSED_EXPLICIT_VERBOSE
    assert res_verb.rewritten_command == "pytest -v tests/"
    assert res_verb.was_modified is False

    # 9. Compound command rewriting
    res_comp = rewriter.rewrite("pytest tests/ && git status")
    assert res_comp.status == RewriteStatus.REWRITTEN
    assert "pytest tests/ -q --tb=short && git status" == res_comp.rewritten_command


def test_subagent_log_sink_engine_distillation() -> None:
    """Verify voluminous test log absorption in subagent blackhole and signal extraction."""
    engine = SubagentLogSinkEngine()

    # Simulate 500 lines of pytest output with 400 passed and 2 failed
    lines = ["test_module.py::test_entry_ok PASSED" for _ in range(400)]
    lines.extend([
        "FAILED tests/test_auth.py::test_token_expiry - AssertionError: assert False",
        "FAILED tests/test_payment.py::test_charge_limit - ConnectionError: timeout",
        "================ 2 failed, 400 passed in 12.34s ================",
    ])
    raw_output = "\n".join(lines)
    assert len(raw_output) > 10000

    task = LogSinkTaskSpec(
        task_id="task-batch-001",
        task_type=LogSinkTaskType.BATCH_TEST,
        command_or_path="pytest tests/",
    )

    card, record = engine.distill_and_quarantine(
        task_spec=task,
        raw_output=raw_output,
        execution_duration_ms=250.0,
        subagent_steps=2,
    )

    assert card.status == LogSinkStatus.FAILURE
    assert card.total_items == 402
    assert card.passed_items == 400
    assert card.failed_items == 2
    assert len(card.error_locations) == 2
    assert "tests/test_auth.py::test_token_expiry" in card.error_locations[0]
    # Noise reduction ratio must exceed 90%
    assert card.noise_reduction_ratio >= 0.90
    assert record.subagent_quarantined_messages == 4
    assert record.raw_tokens_absorbed > 2500
    assert record.delivered_tokens < 100


def test_command_quiet_rewriter_suite_facade() -> None:
    """Verify master suite facade coordination, card rendering, and metrics aggregation."""
    suite = CommandQuietRewriterAndLogSinkSuite()

    # 1. Delegation decision
    assert suite.should_delegate_to_log_sink("pytest tests/unit/") is True
    assert suite.should_delegate_to_log_sink("git log --graph") is True
    assert suite.should_delegate_to_log_sink("echo hello") is False

    # 2. Preflight rewrite via facade
    res = suite.rewrite_preflight("pytest tests/")
    assert res.was_modified is True

    # 3. Log sink distillation via facade
    raw_build_log = (
        "Compiling core v0.1.0\n"
        + "\n".join(f"warning: unused import at line {i}" for i in range(200))
        + "\nerror: failed to resolve symbol AuthContext in src/lib.rs:88\nBuild failed."
    )
    task = LogSinkTaskSpec(
        task_id="task-build-002",
        task_type=LogSinkTaskType.BUILD_INSPECTION,
        command_or_path="cargo build",
    )
    card, record = suite.quarantine_and_distill(task, raw_build_log)
    assert card.status == LogSinkStatus.FAILURE
    assert card.noise_reduction_ratio >= 0.90

    # 4. Render conclusion card for main session
    md = suite.render_conclusion_card(card)
    assert "> ❌ **Subagent Log Sink [build_inspection]**" in md
    assert "Suppressed" in md
    assert "Action" in md

    # 5. Metrics inspection
    metrics = suite.get_aggregate_metrics()
    assert metrics["commands_rewritten"] == 1
    assert metrics["delegated_sink_tasks"] == 1
    assert int(metrics["net_tokens_saved"]) > 0
    assert float(metrics["noise_suppression_ratio"]) >= 0.90
