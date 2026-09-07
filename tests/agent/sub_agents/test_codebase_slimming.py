"""Unit tests for Agentic Codebase Slimming Pipeline.

[INPUT]
- myrm_agent_harness.agent.sub_agents.codebase_slimming (POS: Codebase slimming engine)

[OUTPUT]
- Tests for DeadCodeTopologyScanner, EquivalenceInvarianceGuard, and CodebaseSlimmingPipeline.

[POS]
Unit and behavioral invariance tests for automated codebase slimming.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from myrm_agent_harness.agent.sub_agents.codebase_slimming import (
    CodebaseSlimmingPipeline,
    DeadCodeTopologyScanner,
    EquivalenceInvarianceGuard,
    SlimmingModuleTask,
    SlimmingRiskLevel,
    SlimmingTaskStatus,
)


def test_dead_code_topology_scanner(tmp_path: Path) -> None:
    # 1. Create a workspace with a dead private function and active function
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True)

    file_a = src_dir / "module_a.py"
    file_a.write_text(
        "def _unused_helper():\n"
        "    return 42\n\n"
        "def active_function():\n"
        "    return 'ok'\n",
        encoding="utf-8",
    )

    file_b = src_dir / "main.py"
    file_b.write_text(
        "from src.module_a import active_function\n\n"
        "def run():\n"
        "    return active_function()\n",
        encoding="utf-8",
    )

    report = DeadCodeTopologyScanner.scan_workspace(tmp_path)
    assert report.scanned_files_count == 2
    assert len(report.candidates) >= 1

    cand = next((c for c in report.candidates if c.symbol_name == "_unused_helper"), None)
    assert cand is not None
    assert cand.risk_level == SlimmingRiskLevel.SAFE
    assert cand.estimated_lines_cut >= 2


@pytest.mark.asyncio
async def test_equivalence_invariance_guard(tmp_path: Path) -> None:
    # 1. Passing test command
    verdict = await EquivalenceInvarianceGuard.assert_invariance(
        tmp_path, test_command="echo 'all tests passed'"
    )
    assert verdict.passed is True
    assert verdict.exit_code == 0

    # 2. Failing test command
    failing_verdict = await EquivalenceInvarianceGuard.assert_invariance(
        tmp_path, test_command="exit 1"
    )
    assert failing_verdict.passed is False
    assert failing_verdict.exit_code == 1


@pytest.mark.asyncio
async def test_codebase_slimming_pipeline_execution_and_rollback(tmp_path: Path) -> None:
    src_dir = tmp_path / "pkg"
    src_dir.mkdir(parents=True)

    module_file = src_dir / "worker.py"
    module_file.write_text(
        "def _dead_func():\n"
        "    return 'dead'\n\n"
        "def useful_func():\n"
        "    return 'live'\n",
        encoding="utf-8",
    )

    pipeline = CodebaseSlimmingPipeline(
        workspace_dir=tmp_path,
        test_command="python -c 'import pkg.worker; assert pkg.worker.useful_func() == \"live\"'",
        max_concurrent_workers=2,
    )

    # Mock worker that successfully strips dead code
    async def successful_worker(iso_dir: Path, task: SlimmingModuleTask) -> int:
        target = iso_dir / task.module_path
        target.write_text("def useful_func():\n    return 'live'\n", encoding="utf-8")
        return 2

    ledger, tasks = await pipeline.run_pipeline(successful_worker)
    assert ledger.successful_tasks == 1
    assert ledger.rolled_back_tasks == 0
    assert ledger.lines_cut == 2
    assert "useful_func" in module_file.read_text(encoding="utf-8")
    assert "_dead_func" not in module_file.read_text(encoding="utf-8")

    # Now test rollback when worker introduces breaking change
    broken_pipeline = CodebaseSlimmingPipeline(
        workspace_dir=tmp_path,
        test_command="python -c 'import pkg.worker; assert pkg.worker.useful_func() == \"live\"'",
        max_concurrent_workers=2,
    )

    async def breaking_worker(iso_dir: Path, task: SlimmingModuleTask) -> int:
        target = iso_dir / task.module_path
        # Corrupt the useful_func breaking tests
        target.write_text("def useful_func():\n    return 'broken'\n", encoding="utf-8")
        return 1

    report = broken_pipeline.scan()
    # Artificially assign task to trigger breaking worker
    task = SlimmingModuleTask(
        task_id="task_fail",
        module_path="pkg/worker.py",
        candidates=(),
        test_command=broken_pipeline.test_command,
    )

    updated_task, passed = await broken_pipeline.execute_task_with_worker(task, breaking_worker)
    assert passed is False
    assert updated_task.status == SlimmingTaskStatus.ROLLED_BACK
    # Assert original content intact on live workspace
    assert "useful_func() == 'live'" in "python -c 'import pkg.worker; assert pkg.worker.useful_func() == \"live\"'"
    assert "return 'live'" in module_file.read_text(encoding="utf-8")
