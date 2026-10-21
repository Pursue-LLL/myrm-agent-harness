"""LocalExecutor honours the capability handle bound to the running agent.

A handle without WRITE (the verifier's read/execute handle) makes the workspace read-only for the shell,
Python, agent-started background jobs and the native file operations, while scratch space outside the
workspace stays usable. Execution evidence is recorded only for processes that were actually launched.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from myrm_agent_harness.agent.sub_agents.spawn_capability import derive_spawn_capability, derive_verifier_capability
from myrm_agent_harness.core.security.ocap import CapabilityDeniedError, capability_scope
from myrm_agent_harness.toolkits.code_execution import create_executor
from myrm_agent_harness.toolkits.code_execution.executors.execution_evidence import (
    record_execution,
    track_execution,
)
from myrm_agent_harness.toolkits.code_execution.executors.local.executor import LocalExecutor
from myrm_agent_harness.toolkits.code_execution.executors.models import ExecutionContext
from myrm_agent_harness.toolkits.code_execution.sandbox import detect_sandbox_provider

_requires_os_sandbox = pytest.mark.skipif(
    not detect_sandbox_provider()[1].enabled, reason="OS-level workspace read-only needs a sandbox provider"
)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = (tmp_path / "project").resolve()
    root.mkdir()
    return root


@pytest.fixture
async def executor(workspace: Path) -> AsyncIterator[LocalExecutor]:
    local = create_executor()
    assert isinstance(local, LocalExecutor)
    local.bind_workspace(str(workspace))
    yield local
    await local.close()


def _context(workspace: Path, code: str) -> ExecutionContext:
    return ExecutionContext(
        code=code,
        work_dir=str(workspace),
        workspace_root=str(workspace),
        session_id="chat_capability_scope",
        timeout=30,
    )


def _writer_scope(workspace: Path):
    handle = derive_spawn_capability(
        parent_agent=SimpleNamespace(_last_context={"workspace_path": str(workspace)}),
        agent_type="worker",
        readonly=False,
    )
    return capability_scope(handle)


@_requires_os_sandbox
async def test_read_only_shell_never_reuses_or_taints_the_writable_shell(
    executor: LocalExecutor, workspace: Path
) -> None:
    with _writer_scope(workspace):
        before = await executor.execute_bash(_context(workspace, "touch before.txt"))
        with capability_scope(derive_verifier_capability("verifier")):
            during = await executor.execute_bash(_context(workspace, "touch during.txt"))
        after = await executor.execute_bash(_context(workspace, "touch after.txt"))

    assert before.success
    assert not during.success
    assert after.success
    assert sorted(path.name for path in workspace.glob("*.txt")) == ["after.txt", "before.txt"]


@_requires_os_sandbox
async def test_read_only_shell_can_read_the_workspace_and_use_scratch_space(
    executor: LocalExecutor, workspace: Path, tmp_path: Path
) -> None:
    (workspace / "report.txt").write_text("worker output", encoding="utf-8")
    scratch = Path("/tmp") / f"capability_scope_{tmp_path.name}.txt"

    try:
        with _writer_scope(workspace), capability_scope(derive_verifier_capability("verifier")):
            result = await executor.execute_bash(_context(workspace, f"cat report.txt > {scratch} && cat {scratch}"))
        assert result.success
        assert "worker output" in result.stdout
        assert scratch.read_text(encoding="utf-8") == "worker output"
    finally:
        scratch.unlink(missing_ok=True)


@_requires_os_sandbox
async def test_read_only_shell_cannot_write_a_workspace_that_lives_under_the_scratch_root() -> None:
    root = Path(tempfile.mkdtemp(prefix="capability_scope_ws_", dir="/tmp")).resolve()
    local = create_executor()
    assert isinstance(local, LocalExecutor)
    local.bind_workspace(str(root))
    scratch_file = Path("/tmp") / f"{root.name}_scratch"
    try:
        with _writer_scope(root), capability_scope(derive_verifier_capability("verifier")):
            denied = await local.execute_bash(_context(root, "touch tamper.txt"))
            scratch = await local.execute_bash(_context(root, f"touch {scratch_file}"))
        assert not denied.success
        assert not (root / "tamper.txt").exists()
        assert scratch.success
    finally:
        scratch_file.unlink(missing_ok=True)
        await local.close()
        shutil.rmtree(root, ignore_errors=True)


async def test_python_run_under_a_read_execute_handle_cannot_write_the_workspace(
    executor: LocalExecutor, workspace: Path
) -> None:
    target = workspace / "py_created.txt"

    with _writer_scope(workspace), capability_scope(derive_verifier_capability("verifier")):
        result = await executor.execute(_context(workspace, f"open({str(target)!r}, 'w').write('x')"))

    assert not result.success
    assert not target.exists()


async def test_agent_without_a_handle_keeps_a_writable_workspace(executor: LocalExecutor, workspace: Path) -> None:
    result = await executor.execute_bash(_context(workspace, "touch top_level.txt"))

    assert result.success
    assert (workspace / "top_level.txt").exists()


async def test_native_file_operations_are_denied_without_write(executor: LocalExecutor, workspace: Path) -> None:
    (workspace / "report.txt").write_text("worker output", encoding="utf-8")

    with _writer_scope(workspace), capability_scope(derive_verifier_capability("verifier")):
        assert await executor.read_file(str(workspace / "report.txt")) == "worker output"
        with pytest.raises(CapabilityDeniedError):
            await executor.write_file(str(workspace / "evil.txt"), "tamper")
        with pytest.raises(CapabilityDeniedError):
            await executor.delete_file(str(workspace / "report.txt"))
        with pytest.raises(CapabilityDeniedError):
            await executor.mkdir(str(workspace / "evil_dir"))

    assert sorted(path.name for path in workspace.iterdir()) == ["report.txt"]


async def test_evidence_records_launched_commands_only(executor: LocalExecutor, workspace: Path) -> None:
    with track_execution() as blocked:
        refused = await executor.execute_bash(_context(workspace, "echo a; echo b"))
    with track_execution() as launched:
        ran = await executor.execute_bash(_context(workspace, "echo hi"))

    assert not refused.success
    assert blocked.executed is False
    assert ran.success
    assert launched.executed is True


def test_recording_outside_a_tracked_scope_is_a_no_op() -> None:
    record_execution()

    with track_execution() as evidence:
        assert evidence.executed is False


async def _run_background_job(executor: LocalExecutor, workspace: Path, command: str, *, harness_owned: bool) -> None:
    context = replace(_context(workspace, "sh"), args=["-c", command], harness_owned=harness_owned)
    process = await executor.spawn_background_process(context)
    await asyncio.wait_for(process.wait(), timeout=20)


@_requires_os_sandbox
async def test_agent_started_background_job_cannot_write_a_read_only_workspace(
    executor: LocalExecutor, workspace: Path
) -> None:
    with (
        _writer_scope(workspace),
        capability_scope(derive_verifier_capability("verifier")),
        track_execution() as evidence,
    ):
        await _run_background_job(executor, workspace, "echo x > bg_tamper.txt", harness_owned=False)

    assert not (workspace / "bg_tamper.txt").exists()
    assert evidence.executed is True


async def test_agent_started_background_job_in_a_writable_scope_writes_and_counts_as_evidence(
    executor: LocalExecutor, workspace: Path
) -> None:
    with _writer_scope(workspace), track_execution() as evidence:
        await _run_background_job(executor, workspace, "echo x > bg_ok.txt", harness_owned=False)

    assert (workspace / "bg_ok.txt").exists()
    assert evidence.executed is True


async def test_harness_owned_background_process_ignores_the_agent_capability_and_evidence(
    executor: LocalExecutor, workspace: Path
) -> None:
    with (
        _writer_scope(workspace),
        capability_scope(derive_verifier_capability("verifier")),
        track_execution() as evidence,
    ):
        await _run_background_job(executor, workspace, "echo x > mcp_state.txt", harness_owned=True)

    assert (workspace / "mcp_state.txt").exists()
    assert evidence.executed is False
