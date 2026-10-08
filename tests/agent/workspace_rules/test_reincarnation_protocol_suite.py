# [INPUT]: CrashCause, HeritageSafetyFilterGate, HeritageTabooLesson, InstantHeritageHydrator, ReincarnationCircuitBreaker, ReincarnationDossier, ReincarnationNamespaceAndAgentHeritageInheritanceProtocolSuite, ReincarnationProtocolSuite, SoulLineageRecord, UnfinishedGoal, WorkingHabitShortcut
# [OUTPUT]: test_reincarnation_protocol_suite.py
# [POS]: tests/agent/workspace_rules/test_reincarnation_protocol_suite.py

"""Unit test suite for ReincarnationNamespaceAndAgentHeritageInheritanceProtocolSuite (Item 315).

Verifies:
1. Heritage safety filter gate screening speculative hypotheses and enforcing 2000-char budget.
2. Reincarnation circuit breaker intercepting crashes/model switches and distilling REINCARNATION.md.
3. Instant heritage hydrator injecting prior wisdom and auto-archiving file to eliminate permanent token tax.
4. End-to-end facade coordinating crash distillation, prompt hydration, archive inspection, and lineage pedigree.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import pytest

from myrm_agent_harness.agent.workspace_rules.reincarnation import (
    CrashCause,
    HeritageHydrationResult,
    HeritageSafetyFilterGate,
    HeritageTabooLesson,
    InstantHeritageHydrator,
    ReincarnationCircuitBreaker,
    ReincarnationDossier,
    ReincarnationNamespaceAndAgentHeritageInheritanceProtocolSuite,
    ReincarnationProtocolSuite,
    SoulLineageRecord,
    UnfinishedGoal,
    WorkingHabitShortcut,
)


def test_heritage_safety_filter_gate_speculative_rejection() -> None:
    gate = HeritageSafetyFilterGate()

    # Speculative unverified lesson -> Rejected
    speculative_lesson = HeritageTabooLesson(
        lesson_id="L1",
        trigger_context="Database timeout",
        directive_rule="Maybe the server could be rebooted when latency spikes",
        is_user_verified=False,
    )
    assert gate.is_actionable_lesson(speculative_lesson) is False

    # Actionable imperative taboo -> Accepted
    actionable_taboo = HeritageTabooLesson(
        lesson_id="L2",
        trigger_context="Customer table drop attempt",
        directive_rule="Never run DROP TABLE without dry-run audit",
        is_user_verified=False,
    )
    assert gate.is_actionable_lesson(actionable_taboo) is True

    # User verified rule -> Accepted
    verified_lesson = HeritageTabooLesson(
        lesson_id="L3",
        trigger_context="User admonition",
        directive_rule="Always use snake_case for python variables",
        is_user_verified=True,
    )
    assert gate.is_actionable_lesson(verified_lesson) is True


def test_reincarnation_dossier_markdown_render_and_budget() -> None:
    lineage = SoulLineageRecord(
        generation=2,
        predecessor_model="claude-3-5-sonnet",
        successor_model="claude-3-7-sonnet",
        birth_timestamp="2026-10-08 12:00:00 UTC",
        cumulative_turns=120,
    )

    taboos = (
        HeritageTabooLesson(
            lesson_id="T1",
            trigger_context="OOM kill",
            directive_rule="Never load full 100MB files into memory at once",
            severity="critical",
        ),
    )

    habits = (
        WorkingHabitShortcut(
            shortcut_pattern="t-all",
            expanded_meaning="pytest tests/agent/ -q",
            frequency=5,
        ),
    )

    goals = (
        UnfinishedGoal(
            goal_id="G1",
            description="Complete topic_06 roadmap item 315",
            progress_ratio=0.85,
            blockers=("Need full regression test green",),
        ),
    )

    dossier = ReincarnationDossier(
        lineage=lineage,
        taboo_lessons=taboos,
        working_habits=habits,
        unfinished_goals=goals,
    )

    rendered = dossier.render_markdown()
    assert "REINCARNATION.md: Generation 2" in rendered
    assert "Soul Lineage" in rendered
    assert "Hard Lessons & Taboos" in rendered
    assert "Never load full 100MB files" in rendered
    assert "Working Habits & Short-Circuits" in rendered
    assert "Unfinished Goals" in rendered
    assert len(rendered) <= 2000


def test_reincarnation_circuit_breaker_persists_contract() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        breaker = ReincarnationCircuitBreaker()

        taboo = HeritageTabooLesson(
            lesson_id="T1",
            trigger_context="Accidental git reset",
            directive_rule="Never run git reset --hard on uncommitted workspace",
            severity="critical",
        )

        event = breaker.trigger_reincarnation_circuit(
            workspace_dir=workspace,
            generation=3,
            predecessor_model="gpt-4o",
            successor_model="deepseek-r1",
            cause=CrashCause.CONTEXT_OVERFLOW,
            cumulative_turns=88,
            taboo_lessons=(taboo,),
        )

        assert event.cause == CrashCause.CONTEXT_OVERFLOW
        assert event.generation == 3

        reincarnation_file = workspace / "REINCARNATION.md"
        assert reincarnation_file.is_file()

        content = reincarnation_file.read_text(encoding="utf-8")
        assert "Generation 3" in content
        assert "Never run git reset --hard" in content


def test_instant_heritage_hydrator_injection_and_auto_archive() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        reincarnation_file = workspace / "REINCARNATION.md"
        reincarnation_file.write_text(
            "# [REINCARNATION.md: Generation 4]\n## ⚠️ Hard Lessons\n- Never skip linting",
            encoding="utf-8",
        )

        hydrator = InstantHeritageHydrator()

        # First turn: Heritage detected, injected, and auto-archived
        res = hydrator.hydrate_heritage(workspace, auto_archive=True)
        assert res.has_heritage is True
        assert res.generation == 4
        assert "Inter-Generational Heritage" in res.injected_prompt_block
        assert "Never skip linting" in res.injected_prompt_block
        assert res.is_archived is True

        # Ensure active REINCARNATION.md is pruned from workspace root
        assert not reincarnation_file.exists()

        # Ensure moved to archive
        archive_file = workspace / ".reincarnation_archive" / "reincarnation_gen_4.md"
        assert archive_file.is_file()

        # Second turn: Clean workspace, zero heritage token tax
        res2 = hydrator.hydrate_heritage(workspace, auto_archive=True)
        assert res2.has_heritage is False
        assert res2.injected_prompt_block == ""


def test_reincarnation_facade_end_to_end_lifecycle() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        suite = ReincarnationNamespaceAndAgentHeritageInheritanceProtocolSuite()

        # 1. Trigger catastrophic crash rebirth
        event = suite.trigger_emergency_reincarnation(
            workspace_dir=workspace,
            generation=5,
            predecessor_model="claude-3-opus",
            successor_model="claude-3-7-sonnet",
            cause=CrashCause.MANUAL_MODEL_SWITCH,
            cumulative_turns=200,
            taboo_lessons=(
                HeritageTabooLesson(
                    lesson_id="L10",
                    trigger_context="Prod push",
                    directive_rule="Never push directly to main without PR check",
                    severity="critical",
                ),
            ),
        )
        assert event.generation == 5

        # 2. Hydrate into new session
        hydration = suite.hydrate_workspace_heritage(workspace)
        assert hydration.has_heritage is True
        assert hydration.generation == 5
        assert "Inter-Generational Heritage" in hydration.injected_prompt_block

        # 3. Inspect archive pedigree
        pedigree = suite.inspect_archive_pedigree(workspace)
        assert len(pedigree) == 1
        assert "reincarnation_gen_5.md" in pedigree[0].name

        # Verify alias
        assert ReincarnationProtocolSuite is ReincarnationNamespaceAndAgentHeritageInheritanceProtocolSuite
