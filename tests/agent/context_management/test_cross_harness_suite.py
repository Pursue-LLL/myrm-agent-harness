"""Unit tests for CrossHarnessContextStateASTAndLosslessRehydrationSuite."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

import pytest

from myrm_agent_harness.agent import (
    ArtifactContinuityGateway,
    CrossHarnessContextStateASTAndLosslessRehydrationSuite,
    CrossHarnessSuite,
    HeterogeneousContextHydrationBridge,
    SessionStateASTEngine,
)
from myrm_agent_harness.agent.context_management.cross_harness_ast import (
    ArtifactContinuityReport,
    AstArtifactRef,
    AstMessageRole,
    AstToolInvocation,
    ContextHealthReport,
    HarnessHotSwapBadge,
    HarnessTargetFormat,
    SessionStateAST,
)


def test_top_level_exports() -> None:
    """Verifies that all components are correctly exported and aliases match."""
    assert CrossHarnessSuite is not None
    assert CrossHarnessContextStateASTAndLosslessRehydrationSuite is CrossHarnessSuite
    assert HeterogeneousContextHydrationBridge is not None
    assert ArtifactContinuityGateway is not None
    assert SessionStateASTEngine is not None


def test_session_ast_lifecycle_and_integrity() -> None:
    """Tests creation, appending turns, token estimation, and integrity audit."""
    ast = CrossHarnessSuite.create_session_ast(
        session_id="session-test-001",
        metadata={"user": "Alice", "project": "Myrm"},
    )
    assert ast.session_id == "session-test-001"
    assert len(ast.turns) == 0

    # Append user turn
    ast = CrossHarnessSuite.append_turn(
        ast=ast,
        role=AstMessageRole.USER,
        text_content="Please refactor the database connector and write tests.",
        turn_id="turn-0",
    )

    # Append assistant turn with thinking trace and tool invocation
    tool_call = AstToolInvocation(
        tool_call_id="call-db-1",
        tool_name="bash_execute",
        arguments={"cmd": "pytest tests/test_db.py"},
        result_output="5 passed in 0.4s",
    )
    ast = CrossHarnessSuite.append_turn(
        ast=ast,
        role=AstMessageRole.ASSISTANT,
        text_content="Tests executed cleanly. Proceeding to refactor.",
        thinking_trace="Need to ensure connection pooling handles reconnections.",
        tool_invocations=(tool_call,),
        turn_id="turn-1",
    )

    assert len(ast.turns) == 2
    errors = SessionStateASTEngine.validate_ast_integrity(ast)
    assert len(errors) == 0

    tokens = SessionStateASTEngine.calculate_token_estimate(ast)
    assert tokens > 10

    # Test integrity violation on duplicate turn_id
    duplicate_turn = SessionStateASTEngine.build_turn(
        turn_id="turn-1",
        role=AstMessageRole.USER,
        text_content="Repeat",
    )
    corrupted_ast = SessionStateASTEngine.append_turn(ast, duplicate_turn)
    corrupted_errors = SessionStateASTEngine.validate_ast_integrity(corrupted_ast)
    assert any("Duplicate turn_id" in err for err in corrupted_errors)


def test_heterogeneous_serialization_and_hydration_bilateral() -> None:
    """Tests bilateral conversion across Claude Code, Hermes, Codex, and UHP Standard."""
    ast = CrossHarnessSuite.create_session_ast(session_id="poly-session-42")
    ast = CrossHarnessSuite.append_turn(
        ast=ast,
        role=AstMessageRole.USER,
        text_content="Analyze system logs.",
        turn_id="t-0",
    )
    tool_inv = AstToolInvocation(
        tool_call_id="call-99",
        tool_name="file_search",
        arguments={"pattern": "*.log"},
        result_output="app.log found",
    )
    ast = CrossHarnessSuite.append_turn(
        ast=ast,
        role=AstMessageRole.ASSISTANT,
        text_content="I found app.log. Let me examine the error rates.",
        thinking_trace="Check for 500 status spikes.",
        tool_invocations=(tool_inv,),
        turn_id="t-1",
    )

    # 1. Claude Code
    claude_payload = CrossHarnessSuite.serialize_to_harness(ast, HarnessTargetFormat.CLAUDE_CODE)
    assert claude_payload["format"] == "claude_code"
    assert len(claude_payload["messages"]) == 2
    hydrated_claude = CrossHarnessSuite.hydrate_from_harness(claude_payload, HarnessTargetFormat.CLAUDE_CODE)
    assert len(hydrated_claude.turns) == 2
    assert hydrated_claude.turns[1].thinking_trace == "Check for 500 status spikes."
    assert len(hydrated_claude.turns[1].tool_invocations) == 1
    assert hydrated_claude.turns[1].tool_invocations[0].tool_name == "file_search"

    # 2. Hermes
    hermes_payload = CrossHarnessSuite.serialize_to_harness(ast, HarnessTargetFormat.HERMES)
    assert hermes_payload["agent_state"] == "active"
    assert len(hermes_payload["history"]) == 2
    hydrated_hermes = CrossHarnessSuite.hydrate_from_harness(hermes_payload, HarnessTargetFormat.HERMES)
    assert len(hydrated_hermes.turns) == 2
    assert hydrated_hermes.turns[1].tool_invocations[0].tool_name == "file_search"

    # 3. Codex
    codex_payload = CrossHarnessSuite.serialize_to_harness(ast, HarnessTargetFormat.CODEX)
    assert codex_payload["model"] == "codex"
    hydrated_codex = CrossHarnessSuite.hydrate_from_harness(codex_payload, HarnessTargetFormat.CODEX)
    assert len(hydrated_codex.turns) == 2
    assert hydrated_codex.turns[1].tool_invocations[0].tool_name == "file_search"

    # 4. UHP Standard
    uhp_payload = CrossHarnessSuite.serialize_to_harness(ast, HarnessTargetFormat.UHP_STANDARD)
    assert uhp_payload["uhp_version"] == "1.0"
    hydrated_uhp = CrossHarnessSuite.hydrate_from_harness(uhp_payload, HarnessTargetFormat.UHP_STANDARD)
    assert len(hydrated_uhp.turns) == 2
    assert hydrated_uhp.turns[1].thinking_trace == "Check for 500 status spikes."


def test_hot_swap_readiness_and_status_badge() -> None:
    """Tests context health assessment and frontend hot-swap status badges."""
    ast = CrossHarnessSuite.create_session_ast(session_id="swap-session")
    for idx in range(10):
        ast = CrossHarnessSuite.append_turn(
            ast=ast,
            role=AstMessageRole.USER if idx % 2 == 0 else AstMessageRole.ASSISTANT,
            text_content=f"Turn message payload chunk number {idx} with extensive details.",
            turn_id=f"turn-{idx}",
        )

    # Case A: Generous budget
    health, badge = CrossHarnessSuite.assess_hot_swap_readiness(
        ast=ast,
        source_harness=HarnessTargetFormat.MYRM_NATIVE,
        target_harness=HarnessTargetFormat.CLAUDE_CODE,
        target_token_budget=64000,
    )
    assert isinstance(health, ContextHealthReport)
    assert isinstance(badge, HarnessHotSwapBadge)
    assert health.is_compatible
    assert not health.compression_recommended
    assert badge.is_hot_swappable
    assert "Ready to hot-swap" in badge.status_message

    # Case B: Highly constrained budget (triggering blockage)
    constrained_health, constrained_badge = CrossHarnessSuite.assess_hot_swap_readiness(
        ast=ast,
        source_harness=HarnessTargetFormat.MYRM_NATIVE,
        target_harness=HarnessTargetFormat.HERMES,
        target_token_budget=50,  # Deliberately tiny
    )
    assert not constrained_health.is_compatible
    assert not constrained_badge.is_hot_swappable
    assert "Hot-swap blocked" in constrained_badge.status_message
    assert constrained_health.actionable_remediation is not None


def test_artifact_continuity_gateway_in_sandbox(tmp_path: Path) -> None:
    """Tests physical artifact registration, cryptographic hash verification, and drift detection."""
    sandbox_root = tmp_path / "user_sandbox_volume"
    sandbox_root.mkdir()

    # Create dummy artifact files in sandbox
    chart_path = "output/performance_chart.png"
    (sandbox_root / "output").mkdir()
    chart_file = sandbox_root / chart_path
    chart_file.write_bytes(b"\x89PNG\r\n\x1a\nFakeChartBytesData")

    code_path = "src/calculator.py"
    (sandbox_root / "src").mkdir()
    code_file = sandbox_root / code_path
    code_file.write_text("def add(a, b): return a + b\n", encoding="utf-8")

    ast = CrossHarnessSuite.create_session_ast(session_id="artifact-session")
    ast = CrossHarnessSuite.append_turn(
        ast=ast,
        role=AstMessageRole.USER,
        text_content="Generate charts and math functions.",
        turn_id="t-0",
    )
    ast = CrossHarnessSuite.append_turn(
        ast=ast,
        role=AstMessageRole.ASSISTANT,
        text_content="Assets created.",
        turn_id="t-1",
    )

    # Attach both artifacts
    ast, chart_ref = CrossHarnessSuite.attach_artifact(
        ast=ast,
        turn_id="t-1",
        relative_file_path=chart_path,
        sandbox_volume_root=sandbox_root,
        summary="Performance benchmark chart",
        mime_type="image/png",
    )
    ast, code_ref = CrossHarnessSuite.attach_artifact(
        ast=ast,
        turn_id="t-1",
        relative_file_path=code_path,
        sandbox_volume_root=sandbox_root,
        summary="Python calculator module",
    )

    # 1. Verification of healthy artifacts
    report = CrossHarnessSuite.verify_artifact_continuity(ast, sandbox_volume_root=sandbox_root)
    assert isinstance(report, ArtifactContinuityReport)
    assert report.total_artifacts == 2
    assert report.verified_count == 2
    assert report.is_fully_continuous
    assert len(report.missing_paths) == 0
    assert len(report.hash_mismatches) == 0

    # 2. Tampering test (simulate file mutation drift)
    code_file.write_text("def add(a, b): return a + b + 99999\n", encoding="utf-8")
    drift_report = CrossHarnessSuite.verify_artifact_continuity(ast, sandbox_volume_root=sandbox_root)
    assert not drift_report.is_fully_continuous
    assert len(drift_report.hash_mismatches) == 1
    assert "calculator.py" in drift_report.hash_mismatches[0]

    # 3. Missing file test
    chart_file.unlink()
    missing_report = CrossHarnessSuite.verify_artifact_continuity(ast, sandbox_volume_root=sandbox_root)
    assert not missing_report.is_fully_continuous
    assert chart_path in missing_report.missing_paths
