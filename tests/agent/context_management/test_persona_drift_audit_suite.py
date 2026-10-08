# [INPUT] persona_drift_audit package modules
# [OUTPUT] Comprehensive unit test suite for deterministic persona memory drift audit and reconciliation
# [POS] Tests for 4D bad-smell tagging, "Read only until my yes" diff gate, backup safety, and workspace lifecycle

"""Comprehensive unit tests for DeterministicPersonaMemoryDriftAuditSuite."""

from pathlib import Path
import pytest

from myrm_agent_harness.agent import (
    DeterministicPersonaMemoryDriftAuditAndLineByLineReconciliationSuite,
    DeterministicPersonaMemoryDriftAuditSuite,
    LineByLineRealityReconciler,
    PurificationDiffEngine,
)
from myrm_agent_harness.agent.context_management import (
    AuditLineSmell,
    BadSmellCategory,
    FileDriftAuditResult,
    PersonaFileKind,
    PurificationExecutionResult,
    ReconciliationDiffPlan,
)


def test_top_level_exports() -> None:
    """Verify all public types, facades, and aliases are exported correctly."""
    assert (
        DeterministicPersonaMemoryDriftAuditAndLineByLineReconciliationSuite
        is DeterministicPersonaMemoryDriftAuditSuite
    )


def test_four_dimensional_bad_smell_tagging(tmp_path: Path) -> None:
    """Verify detection of NO_OP, DUPLICATE, CONTRADICTORY, and STALE flaws."""
    # Create workspace with one real file
    (tmp_path / "vite.config.ts").write_text("// active vite config", encoding="utf-8")

    memory_content = """# Core Memory & Guidelines
- Primary framework is React and Vite.
- We had a great chat today about architecture.
- Always use strict TypeScript types.
- Always use strict TypeScript types.
- Keep it brief and concise.
- Always provide detailed and exhaustive explanations.
- Configuration is loaded from legacy_webpack.config.js.
"""

    audit_result = LineByLineRealityReconciler.audit_persona_file(
        file_path=str(tmp_path / "MEMORY.md"),
        content=memory_content,
        file_kind="MEMORY",
        workspace_root=tmp_path,
    )

    assert audit_result.has_flaws is True
    assert audit_result.total_lines == 8
    assert audit_result.healthy_score < 100
    assert audit_result.estimated_token_waste > 0

    smell_types = {flag.smell for flag in audit_result.flagged_lines}
    assert "NO_OP" in smell_types         # line 3: "had a great chat..."
    assert "DUPLICATE" in smell_types     # line 5: repeated "Always use strict TypeScript types"
    assert "CONTRADICTORY" in smell_types # line 7: detailed explanations vs brief
    assert "STALE" in smell_types         # line 8: legacy_webpack.config.js does not exist


def test_read_only_until_my_yes_diff_engine(tmp_path: Path) -> None:
    """Verify strictly read-only diff generation and human confirmation enforcement."""
    file_path = tmp_path / "SOUL.md"
    original_text = (
        "- You are a helpful software engineer.\n"
        "- The user was happy with the result.\n"
        "- Follow PEP8 conventions.\n"
    )
    file_path.write_text(original_text, encoding="utf-8")

    audit_res = LineByLineRealityReconciler.audit_persona_file(
        file_path=str(file_path),
        content=original_text,
        file_kind="SOUL",
    )
    assert len(audit_res.flagged_lines) == 1
    assert audit_res.flagged_lines[0].smell == "NO_OP"

    # 1. Generate diff plan (strictly read-only)
    diff_plan = PurificationDiffEngine.generate_diff_plan(audit_res, original_text)
    assert diff_plan.requires_confirmation is True
    assert 2 in diff_plan.removed_line_numbers
    assert "The user was happy with the result." not in diff_plan.purified_content
    assert "Follow PEP8 conventions." in diff_plan.purified_content

    # Verify original file on disk was NOT mutated
    assert file_path.read_text(encoding="utf-8") == original_text

    # 2. Rejection when user_confirmed=False
    reject_res = PurificationDiffEngine.apply_purification(
        diff_plan=diff_plan,
        user_confirmed=False,
    )
    assert reject_res.applied is False
    assert "rejected" in reject_res.message.lower()
    assert file_path.read_text(encoding="utf-8") == original_text

    # 3. Successful execution when user_confirmed=True
    confirm_res = PurificationDiffEngine.apply_purification(
        diff_plan=diff_plan,
        user_confirmed=True,
        create_backup=True,
    )
    assert confirm_res.applied is True
    assert confirm_res.backup_path is not None
    assert Path(confirm_res.backup_path).exists()
    assert Path(confirm_res.backup_path).read_text(encoding="utf-8") == original_text

    # Verify disk file updated
    updated_disk_text = file_path.read_text(encoding="utf-8")
    assert "The user was happy with the result." not in updated_disk_text
    assert "Follow PEP8 conventions." in updated_disk_text


def test_deterministic_persona_audit_suite_workspace_lifecycle(tmp_path: Path) -> None:
    """Verify complete workspace discovery, auditing, and purification lifecycle."""
    # Populate the canonical 4 persona files
    (tmp_path / "SOUL.md").write_text(
        "- Master architect persona.\n- Hello world! Looking forward to helping.\n",
        encoding="utf-8",
    )
    (tmp_path / "USER.md").write_text(
        "- User prefers Python.\n",
        encoding="utf-8",
    )
    (tmp_path / "MEMORY.md").write_text(
        "- Always use tabs for indentation.\n- Always use spaces for indentation.\n",
        encoding="utf-8",
    )
    (tmp_path / "AGENTS.md").write_text(
        "- Single agent topology.\n",
        encoding="utf-8",
    )

    # 1. Audit entire workspace
    audit_results = DeterministicPersonaMemoryDriftAuditSuite.audit_workspace(tmp_path)
    assert len(audit_results) == 4

    flawed = [r for r in audit_results if r.has_flaws]
    assert len(flawed) == 2  # SOUL.md (NO_OP) and MEMORY.md (CONTRADICTORY)

    # 2. Generate diff plans
    plans = DeterministicPersonaMemoryDriftAuditSuite.generate_diff_plans(audit_results)
    assert len(plans) == 2

    # 3. Apply plans with user consent
    for p in plans:
        res = DeterministicPersonaMemoryDriftAuditSuite.apply_plan(p, user_confirmed=True)
        assert res.applied is True

    # 4. Re-audit workspace: should be purified and flawless
    re_audited = DeterministicPersonaMemoryDriftAuditSuite.audit_workspace(tmp_path)
    flawed_after = [r for r in re_audited if r.has_flaws]
    assert len(flawed_after) == 0
    assert all(r.healthy_score == 100 for r in re_audited)
