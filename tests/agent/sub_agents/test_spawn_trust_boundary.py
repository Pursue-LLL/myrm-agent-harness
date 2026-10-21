"""What a delegated subagent is allowed to touch, driven from the `delegate_task` tool parameters.

The model supplies `context_files` and `context`; the capability handle and the child's runtime
context must come from the parent's real workspace and the user's authorized directories, never from
those parameters. Every test enters through the production tool function and inspects what the
parent hands to `_spawn_child` and the handle the child run is bound to at that moment.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import create_delegate_task_tool
from myrm_agent_harness.agent.security.session_access import set_session_access_roots
from myrm_agent_harness.agent.sub_agents.spawn_capability import derive_spawn_capability
from myrm_agent_harness.agent.sub_agents.types import SubagentConfig, SubAgentResult
from myrm_agent_harness.core.security.ocap import (
    CapabilityAction,
    CapabilityHandle,
    capability_scope,
    check_capability_access,
    get_current_capability,
    sign_capability_handle,
)
from myrm_agent_harness.core.security.types import AccessRoot, PathPolicy, SecurityConfig

_READ = CapabilityAction.READ
_WRITE = CapabilityAction.WRITE
_EXECUTE = CapabilityAction.EXECUTE


@pytest.fixture(autouse=True)
def _isolated_delegate_state() -> Iterator[None]:
    set_session_access_roots(())
    yield
    set_session_access_roots(())


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = (tmp_path / "workspace").resolve()
    (root / "src").mkdir(parents=True)
    return root


@pytest.fixture
def external(tmp_path: Path) -> Path:
    """A directory outside the workspace, standing in for something the user authorized."""
    root = (tmp_path / "downloads").resolve()
    root.mkdir()
    return root


def _make_parent(
    workspace: Path,
    *,
    path_policy: PathPolicy | None = None,
    parallel_write_batch: bool = False,
) -> MagicMock:
    parent = MagicMock()
    parent.config = SimpleNamespace(security_config=SecurityConfig(path_policy=path_policy or PathPolicy()))
    parent.engine_params = {}
    parent._parallel_write_batch_active = parallel_write_batch
    parent._last_context = {
        "workspace_path": str(workspace),
        "session_id": "chat_A",
        "user_id": "user_1",
        "workspaces_storage_root": str(workspace.parent / "storage"),
    }
    parent.bound_handles = []

    async def spawn_child(**_: object) -> SubAgentResult:
        parent.bound_handles.append(get_current_capability())
        return SubAgentResult(task_id="t", success=True, result="ok", agent_type="coder")

    parent._spawn_child = AsyncMock(side_effect=spawn_child)
    return parent


async def _delegate(parent: MagicMock, **params: object) -> dict[str, object]:
    """Call the real delegate_task tool function and return the child context it built."""
    catalog = AsyncMock()
    catalog.resolve = AsyncMock(return_value=SubagentConfig(system_prompt="worker"))
    tool = create_delegate_task_tool(parent, lambda: [], catalog)
    result = await tool.coroutine(agent_type="coder", objective="do the work", wait=True, **params)
    assert result["success"] is True, result
    child_context = parent._spawn_child.call_args.kwargs["context"]
    assert isinstance(child_context, dict)
    assert not any(isinstance(value, CapabilityHandle) for value in child_context.values())
    return child_context


def _spawned_handle(parent: MagicMock) -> CapabilityHandle:
    """The handle the child run was bound to when the parent spawned it."""
    handle = parent.bound_handles[-1]
    assert isinstance(handle, CapabilityHandle)
    return handle


def _allowed(handle: CapabilityHandle, action: CapabilityAction, target: Path | str) -> bool:
    return check_capability_access(action, str(target), handle=handle)


def _init_git_repo(root: Path) -> None:
    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)

    git("init", "-q")
    (root / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    git("add", "-A")
    git("-c", "user.name=test", "-c", "user.email=test@example.com", "commit", "-qm", "init")


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git for worktree isolation")
async def test_parallel_writer_in_git_workspace_can_write_the_parent_workspace(workspace: Path) -> None:
    _init_git_repo(workspace)
    parent = _make_parent(workspace, parallel_write_batch=True)

    child_context = await _delegate(parent)
    handle = _spawned_handle(parent)

    assert child_context["workspace_path"] != str(workspace), "the parallel batch must have been isolated"
    assert _allowed(handle, _WRITE, workspace / "src" / "a.py")
    assert _allowed(handle, _EXECUTE, workspace)
    assert _allowed(handle, _WRITE, Path(str(child_context["workspace_path"])) / "new.txt")
    assert not _allowed(handle, _WRITE, workspace.parent / "elsewhere.txt")


async def test_model_context_cannot_rebind_the_child_workspace(workspace: Path, tmp_path: Path) -> None:
    parent = _make_parent(workspace)
    forged: dict[str, object] = {
        "workspace_path": "/",
        "session_id": "chat_B",
        "user_id": "user_2",
        "workspaces_storage_root": str(tmp_path / "other_storage"),
        "_isolated_parent_workspace": "/tmp/elsewhere",
        "note": "free-form data the child may read in its task text",
    }

    child_context = await _delegate(parent, context=forged)
    handle = _spawned_handle(parent)

    assert child_context["workspace_path"] == str(workspace)
    assert child_context["session_id"] == "chat_A"
    assert child_context["user_id"] == "user_1"
    assert child_context["workspaces_storage_root"] == str(workspace.parent / "storage")
    assert "_isolated_parent_workspace" not in child_context
    assert "note" not in child_context
    assert not _allowed(handle, _WRITE, "/etc/hosts")
    task = parent._spawn_child.call_args.kwargs["task_description"]
    assert "free-form data the child may read" in task


@pytest.mark.parametrize(
    "context_file",
    ["/", "/etc/hosts", "../outside.txt", "~/.ssh/id_rsa"],
    ids=["filesystem_root", "system_file", "relative_traversal", "forbidden_home_zone"],
)
async def test_unauthorized_context_files_do_not_widen_the_handle(workspace: Path, context_file: str) -> None:
    parent = _make_parent(workspace)

    await _delegate(parent, context_files=[context_file])
    handle = _spawned_handle(parent)

    assert not _allowed(handle, _WRITE, "/etc/hosts")
    assert not _allowed(handle, _WRITE, os.path.expanduser("~/.ssh/id_rsa"))
    assert not _allowed(handle, _WRITE, workspace.parent / "outside.txt")
    assert _allowed(handle, _WRITE, workspace / "src" / "a.py")


@pytest.mark.parametrize("malformed", ["bad\x00name", "/tmp/x\x00"], ids=["nul_relative", "nul_absolute"])
async def test_malformed_context_file_is_dropped_instead_of_failing_the_spawn(workspace: Path, malformed: str) -> None:
    parent = _make_parent(workspace)

    await _delegate(parent, context_files=[malformed, "src/a.py"])
    handle = _spawned_handle(parent)

    assert _allowed(handle, _WRITE, workspace / "src" / "a.py")
    assert not _allowed(handle, _WRITE, "/etc/hosts")


def test_unencodable_context_file_is_dropped_when_deriving_the_handle(workspace: Path) -> None:
    handle = derive_spawn_capability(
        parent_agent=_make_parent(workspace),
        agent_type="coding",
        readonly=False,
        context_files=["bad\ud800name"],
    )

    assert handle.scope.paths == (f"{workspace}/**",)


async def test_parent_without_security_config_authorizes_no_directory_outside_the_workspace(
    workspace: Path, external: Path
) -> None:
    parent = _make_parent(workspace)
    parent.config = SimpleNamespace()

    await _delegate(parent, context_files=[str(external / "q3.pdf"), "src/a.py"])
    handle = _spawned_handle(parent)

    assert not _allowed(handle, _READ, external / "q3.pdf")
    assert _allowed(handle, _WRITE, workspace / "src" / "a.py")


async def test_authorized_directory_stays_reachable_through_context_files(workspace: Path, external: Path) -> None:
    policy = PathPolicy(access_roots=(AccessRoot(path=str(external), writable=True),))
    parent = _make_parent(workspace, path_policy=policy)

    await _delegate(parent, context_files=[str(external / "q3.pdf")])
    handle = _spawned_handle(parent)

    assert _allowed(handle, _READ, external / "q3.pdf")
    assert _allowed(handle, _WRITE, external / "q3.pdf")
    assert not _allowed(handle, _READ, external / "other.pdf")


async def test_session_granted_directory_stays_reachable_through_context_files(workspace: Path, external: Path) -> None:
    set_session_access_roots((AccessRoot(path=str(external), writable=True),))
    parent = _make_parent(workspace)

    await _delegate(parent, context_files=[str(external / "q3.pdf")])
    handle = _spawned_handle(parent)

    assert _allowed(handle, _WRITE, external / "q3.pdf")


async def test_read_only_authorized_directory_is_not_writable_through_a_writing_child(
    workspace: Path, external: Path
) -> None:
    policy = PathPolicy(access_roots=(AccessRoot(path=str(external), writable=False),))
    target = external / "report.pdf"

    writing_parent = _make_parent(workspace, path_policy=policy)
    await _delegate(writing_parent, context_files=[str(target)])
    reading_parent = _make_parent(workspace, path_policy=policy)
    await _delegate(reading_parent, context_files=[str(target)], readonly=True)
    writer = _spawned_handle(writing_parent)
    reader = _spawned_handle(reading_parent)

    assert not _allowed(writer, _WRITE, target)
    assert _allowed(reader, _READ, target)
    assert not _allowed(reader, _WRITE, target)


async def test_grandchild_of_a_read_only_parent_is_read_only(workspace: Path) -> None:
    parent_handle = derive_spawn_capability(
        parent_agent=SimpleNamespace(_last_context={"workspace_path": str(workspace)}),
        agent_type="explorer",
        readonly=True,
    )
    parent = _make_parent(workspace)

    with capability_scope(parent_handle):
        await _delegate(parent, readonly=False)
    handle = _spawned_handle(parent)

    assert handle.actions == frozenset({_READ})
    assert not _allowed(handle, _WRITE, workspace / "src" / "a.py")
    assert handle.parent_handle_id == parent_handle.handle_id
    assert handle.expires_at <= parent_handle.expires_at


async def test_expired_parent_handle_refuses_the_spawn(workspace: Path) -> None:
    live = derive_spawn_capability(
        parent_agent=SimpleNamespace(_last_context={"workspace_path": str(workspace)}),
        agent_type="worker",
        readonly=False,
    )
    expired = replace(live, expires_at=time.monotonic() - 1.0)
    expired = replace(expired, signature=sign_capability_handle(expired))
    parent = _make_parent(workspace)
    catalog = AsyncMock()
    catalog.resolve = AsyncMock(return_value=SubagentConfig(system_prompt="worker"))

    with capability_scope(expired):
        result = await create_delegate_task_tool(parent, lambda: [], catalog).coroutine(
            agent_type="coder", objective="do the work", wait=True
        )

    assert result["success"] is False
    assert "Subagent capability denied" in str(result["error"])
    parent._spawn_child.assert_not_awaited()


async def test_council_and_alternatives_children_do_not_inherit_model_context(workspace: Path) -> None:
    from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_cognitive import execute_cognitive_mode

    parent = _make_parent(workspace)
    parent._subagent_manager = MagicMock()
    catalog = AsyncMock()
    catalog.resolve = AsyncMock(return_value=SubagentConfig(system_prompt="expert"))

    with (
        patch(
            "myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_cognitive._preflight_cost_check",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "myrm_agent_harness.agent.sub_agents.orchestrator.run_alternatives",
            new_callable=AsyncMock,
            return_value=[],
        ) as run_alternatives,
    ):
        await execute_cognitive_mode(
            mode="alternatives",
            parent_agent=parent,
            catalog=catalog,
            objective="compare designs",
            expert_agent_types=["a", "b"],
            context={"session_id": "chat_B", "_isolated_parent_workspace": "/tmp/elsewhere", "note": "text only"},
            context_files=[],
            tool_registry_getter=lambda: [],
            readonly=False,
            cross_review_rounds=1,
            chair_agent_type=None,
            cancel_token=None,
            session_id="chat_A",
            allowed_types=None,
        )

    child_context = run_alternatives.call_args.kwargs["context"]
    assert child_context["session_id"] == "chat_A"
    assert "_isolated_parent_workspace" not in child_context
    assert "note" not in child_context
