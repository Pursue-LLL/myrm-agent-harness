"""Tests for the sandbox write guard in LocalFileOpsMixin.

``_guard_write`` is the single choke point every native mutation in the mixin
passes through, so these tests exercise it through the real ``LocalExecutor``
rather than a stand-in: a regression in the mixin or in the shared path rules
shows up here as a changed verdict.
"""

import pytest

from myrm_agent_harness.core.context_vars import protected_paths_var
from myrm_agent_harness.toolkits.code_execution.config import ExecutionConfig
from myrm_agent_harness.toolkits.code_execution.executors.local.executor import LocalExecutor


@pytest.fixture
def executor(tmp_path):
    ex = LocalExecutor(ExecutionConfig())
    ex.bind_workspace(str(tmp_path))
    return ex


@pytest.fixture(autouse=True)
def _no_goal_protection():
    protected_paths_var.set(())
    yield
    protected_paths_var.set(())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "reason"),
    [
        ("evidence", "evidence directory itself"),
        ("evidence/report.pdf", "evidence directory"),
        ("user_inputs", "user input directory itself"),
        ("user_inputs/notes.csv", "user input directory"),
        (".env", "credential file"),
        ("secrets/key.pem", "credential key"),
        ("AGENTS.md", "persona instruction file"),
        ("nested/dir/SOUL.md", "nested persona instruction file"),
    ],
)
async def test_write_refuses_protected_paths(executor, path, reason):
    with pytest.raises(PermissionError):
        await executor.write_file(path, "content")


@pytest.mark.asyncio
async def test_write_refuses_goal_protected_path(executor):
    protected_paths_var.set(("data/sales.csv",))
    with pytest.raises(PermissionError):
        await executor.write_file("data/sales.csv", "1,2,3")


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["artifacts/report.md", "working/notes.txt", "src/main.py"])
async def test_write_allows_ordinary_paths(executor, path):
    await executor.write_file(path, "content")
    assert executor._current_workspace is not None
    assert (executor._current_workspace / path).read_text() == "content"


@pytest.mark.asyncio
async def test_read_of_evidence_stays_allowed(executor, tmp_path):
    (tmp_path / "evidence").mkdir()
    (tmp_path / "evidence" / "source.pdf").write_text("original")

    assert await executor.read_file("evidence/source.pdf") == "original"


@pytest.mark.asyncio
async def test_append_and_delete_refuse_protected_paths(executor):
    with pytest.raises(PermissionError):
        await executor.append_file("evidence/log.txt", "line")
    with pytest.raises(PermissionError):
        await executor.delete_file("evidence/source.pdf")


@pytest.mark.asyncio
async def test_configured_readonly_root_still_wins(executor, tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    executor._readonly_paths = [str(locked)]

    with pytest.raises(PermissionError, match="read-only"):
        await executor.write_file("locked/anything.txt", "content")
