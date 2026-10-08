"""Unit tests for WorkBuddy Handoff-then-Compact suite and checkpoint compiler."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.handoff_checkpoint import (
    HandoffCompactStage,
    HandoffThenCompactResult,
    TaskCheckpoint,
    WorkBuddyHandoffThenCompactSuite,
)


def test_checkpoint_compilation_and_markdown_roundtrip() -> None:
    """Test 6-dimensional checkpoint compilation, markdown rendering, and roundtrip parsing."""
    suite = WorkBuddyHandoffThenCompactSuite()
    compiler = suite.compiler

    cp = compiler.compile_checkpoint(
        session_id="session_alpha_101",
        ultimate_goal="Implement distributed rate limiter across all ingress nodes",
        completed_items=["Designed Redis Lua script token bucket", "Added unit tests for boundary bursts"],
        important_constraints=["Zero dependency on external heavy frameworks", "Latency must stay under 2ms"],
        modified_files=["src/limiter/bucket.py", "tests/limiter/test_bucket.py"],
        pending_issues=["Handle cluster split-brain edge cases"],
        next_actions=["Deploy canary deployment to node cluster", "Run load simulation"],
    )

    assert cp.session_id == "session_alpha_101"
    assert len(cp.checkpoint_hash) == 16
    assert len(cp.completed_items) == 2
    assert len(cp.important_constraints) == 2

    # Render Markdown
    rendered_md = compiler.render_markdown(cp)
    assert "<!-- HANDOFF_TASK_CHECKPOINT:START session=session_alpha_101" in rendered_md
    assert "## 1. 最终目标 (Ultimate Goal)" in rendered_md
    assert "## 4. 修改过的文件 (Modified Files)" in rendered_md
    assert "`src/limiter/bucket.py`" in rendered_md

    # Roundtrip parse
    parsed_cp = compiler.parse_markdown(rendered_md)
    assert parsed_cp.session_id == cp.session_id
    assert parsed_cp.ultimate_goal == cp.ultimate_goal
    assert parsed_cp.completed_items == cp.completed_items
    assert parsed_cp.important_constraints == cp.important_constraints
    assert parsed_cp.modified_files == cp.modified_files
    assert parsed_cp.pending_issues == cp.pending_issues
    assert parsed_cp.next_actions == cp.next_actions
    assert parsed_cp.checkpoint_hash == cp.checkpoint_hash


def test_handoff_then_compact_pipeline_success() -> None:
    """Test successful two-phase handoff-then-compact workflow."""
    suite = WorkBuddyHandoffThenCompactSuite()
    session_id = "session_beta_202"

    persisted_files: dict[str, str] = {}

    def mock_writer(content: str) -> str:
        uri = f"workspace://checkpoints/{session_id}/TASK_CHECKPOINT.md"
        persisted_files[uri] = content
        return uri

    def mock_compactor(pre_tokens: int) -> tuple[int, bool]:
        # Compact 20,000 tokens down to 4,000 tokens
        return 4_000, True

    res: HandoffThenCompactResult = suite.execute_handoff_then_compact(
        session_id=session_id,
        ultimate_goal="Migrate PostgreSQL schema to version 42",
        completed_items=["Drafted migration DDL", "Validated foreign key constraints"],
        important_constraints=["Zero downtime migration"],
        modified_files=["migrations/0042_upgrade.sql"],
        pending_issues=[],
        next_actions=["Apply DDL on staging"],
        pre_compact_tokens=20_000,
        persistence_writer=mock_writer,
        compaction_runner=mock_compactor,
    )

    assert res.success is True
    assert res.stage == HandoffCompactStage.COMPACTED
    assert res.pre_compact_tokens == 20_000
    assert res.post_compact_tokens == 4_000
    assert res.tokens_reduced == 16_000
    assert res.compression_ratio == 0.8
    assert res.checkpoint_uri in persisted_files

    # Check recovery prompt generation
    prompt = suite.render_restoration_prompt(session_id)
    assert prompt is not None
    assert "Context compacted. Read handoff checkpoint below to resume task execution" in prompt
    assert "Migrate PostgreSQL schema to version 42" in prompt


def test_guard_rejects_empty_goal_or_incomplete_checkpoint() -> None:
    """Test safety guard forbids lossy compaction when ultimate goal is missing."""
    suite = WorkBuddyHandoffThenCompactSuite()

    res = suite.execute_handoff_then_compact(
        session_id="session_gamma_303",
        ultimate_goal="   ",  # blank goal
        completed_items=["Done something"],
    )

    assert res.success is False
    assert "ultimate_goal cannot be empty or blank" in (res.error_message or "")
    assert res.tokens_reduced == 0


def test_checkpoint_persistence_failure_aborts_compaction() -> None:
    """Test persistence failure aborts compaction immediately to avoid context loss."""
    suite = WorkBuddyHandoffThenCompactSuite()

    def failing_writer(content: str) -> str:
        raise OSError("Permission denied writing to workspace checkpoint volume")

    res = suite.execute_handoff_then_compact(
        session_id="session_delta_404",
        ultimate_goal="Build real-time observability telemetry",
        pre_compact_tokens=15_000,
        persistence_writer=failing_writer,
    )

    assert res.success is False
    assert res.stage == HandoffCompactStage.COMPILED
    assert "Checkpoint persistence failed" in (res.error_message or "")
    assert "aborted compaction to prevent state loss" in (res.error_message or "")
