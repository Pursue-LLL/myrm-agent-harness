"""Unit tests for Quiet command rewriter, output spill, and Subagent context firewall.

Verifies transparent command rewriting with quiet flags, oversized output disk spilling
with head-tail diagnostics, and Subagent firewall model downgrade and isolation.
"""

from __future__ import annotations

from pathlib import Path

from myrm_agent_harness.runtime.context.output_spill_to_disk_middleware import (
    OutputSpillToDiskMiddleware,
)
from myrm_agent_harness.runtime.context.quiet_command_rewriter_hook import (
    QuietCommandRewriterHook,
)
from myrm_agent_harness.runtime.context.quiet_command_spill_types import CommandCategory
from myrm_agent_harness.runtime.context.subagent_context_firewall import (
    SubagentContextFirewall,
)


def test_quiet_command_rewriter_hook() -> None:
    """Verifies targeted insertion of quiet flags and preservation of explicit verbosity."""
    hook = QuietCommandRewriterHook(enabled=True)

    # 1. Pytest
    r1 = hook.rewrite_command("pytest tests/unit")
    assert r1.is_rewritten is True
    assert r1.rewritten_command == "pytest tests/unit -q"
    assert r1.category == CommandCategory.TEST_RUNNER

    # 1b. Pytest already quiet
    r1_noop = hook.rewrite_command("pytest tests/unit -q")
    assert r1_noop.is_rewritten is False

    # 1c. Explicit verbose intent respected
    r1_verb = hook.rewrite_command("pytest -v tests/unit")
    assert r1_verb.is_rewritten is False
    assert r1_verb.reason == "explicit_verbose_intent_detected"

    # 2. NPM test
    r2 = hook.rewrite_command("npm test")
    assert r2.is_rewritten is True
    assert r2.rewritten_command == "npm test --silent"

    # 3. Git status
    r3 = hook.rewrite_command("git status")
    assert r3.is_rewritten is True
    assert r3.rewritten_command == "git status -s"
    assert r3.category == CommandCategory.VCS

    # 4. Cargo test
    r4 = hook.rewrite_command("cargo test --all")
    assert r4.is_rewritten is True
    assert r4.rewritten_command == "cargo test --all -q"

    # 5. Pip install
    r5 = hook.rewrite_command("pip install torch")
    assert r5.is_rewritten is True
    assert r5.rewritten_command == "pip install torch -q"

    # 6. Unmatched command
    r6 = hook.rewrite_command("echo 'hello world'")
    assert r6.is_rewritten is False


def test_output_spill_to_disk_oversized(tmp_path: Path) -> None:
    """Outputs exceeding 30k chars must spill to disk and yield head-tail snippets."""
    middleware = OutputSpillToDiskMiddleware(
        max_output_chars=1000,  # Lower limit for testing
        spill_directory=tmp_path,
        head_preview_chars=100,
        tail_preview_chars=150,
    )

    oversized_output = (
        "START_HEADER: Initializing cluster build...\n"
        + "PROGRESS: Building package chunk...\n" * 80
        + "FAILURE_TAIL: Assertion failed at test_worker.py:42 - ConnectionRefused\n"
        + "EXIT: Build exited with status 1"
    )
    assert len(oversized_output) > 1000

    receipt = middleware.process_output(
        output_text=oversized_output,
        exit_code=1,
        command="cargo test",
    )

    assert receipt.is_spilled is True
    assert receipt.exit_code == 1
    assert receipt.spilled_file_path is not None
    assert receipt.saved_tokens > 0

    # Ensure spilled file exists on disk with full fidelity
    spill_file = Path(receipt.spilled_file_path)
    assert spill_file.exists()
    assert spill_file.read_text(encoding="utf-8") == oversized_output

    # Context snippet must retain head, tail, and path pointer
    assert "START_HEADER" in receipt.context_snippet
    assert "FAILURE_TAIL" in receipt.context_snippet
    assert str(spill_file.resolve()) in receipt.context_snippet
    assert "Command Output Exceeded Safe Limit" in receipt.context_snippet


def test_output_spill_normal_passthrough(tmp_path: Path) -> None:
    """Outputs within threshold must be passed through directly without disk spill."""
    middleware = OutputSpillToDiskMiddleware(
        max_output_chars=5000,
        spill_directory=tmp_path,
    )

    normal_output = "PASS: 12 tests passed in 0.45s."
    receipt = middleware.process_output(output_text=normal_output, exit_code=0)

    assert receipt.is_spilled is False
    assert receipt.spilled_file_path is None
    assert receipt.context_snippet == normal_output
    assert receipt.saved_tokens == 0


def test_subagent_context_firewall_isolation_and_downgrade() -> None:
    """Firewall identifies noisy tasks, downgrades model, and isolates raw intermediate logs."""
    firewall = SubagentContextFirewall()

    # 1. Identification & Model Downgrade
    assert firewall.should_isolate("deep_log_analysis_job") is True
    assert firewall.should_isolate("simple_chat") is False

    downgraded = firewall.select_model_tier("deep_log_analysis_job", main_model="gpt-4o")
    assert downgraded == "flash"

    normal_model = firewall.select_model_tier("simple_chat", main_model="gpt-4o")
    assert normal_model == "gpt-4o"

    # 2. Filtering & Delivery
    raw_intermediate_log = "FATAL ERROR 500: Database lock timeout\n" * 200  # ~7,000 chars
    concise_summary = "Analysis conclusion: Database deadlock was caused by concurrent transaction in worker 3."

    result = firewall.filter_and_deliver(
        task_name="deep_log_analysis_job",
        intermediate_output=raw_intermediate_log,
        summary_conclusion=concise_summary,
    )

    assert result.task_name == "deep_log_analysis_job"
    assert result.assigned_model == "flash"
    assert result.raw_intermediate_chars == len(raw_intermediate_log)
    assert result.delivered_summary_chars == len(concise_summary)
    assert result.blocked_intermediate_tokens > 1500
    assert result.net_saved_main_session_tokens > 1500
    assert result.summary_text == concise_summary
