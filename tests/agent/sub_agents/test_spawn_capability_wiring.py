"""The capability handle a delegated subagent runs under, driven through the real child-run chain.

A scripted model issues a real `file_write_tool` call inside a real `BaseAgent.run`, which performs the
production `setup_workspace`, tool interceptor and file executor. Only the model is scripted. The handle
is minted by the production `derive_spawn_capability` from the parent's workspace and bound by
`capability_scope`, exactly as `delegate_task_tool` does for a spawned child.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import BaseTool, StructuredTool

from myrm_agent_harness.agent.base_agent import BaseAgent
from myrm_agent_harness.agent.meta_tools.bash.bash_code_execute_tool import create_bash_code_execute_tool
from myrm_agent_harness.agent.meta_tools.file_ops.file_edit_tool import create_file_edit_tool
from myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool import create_file_read_tool
from myrm_agent_harness.agent.meta_tools.file_ops.file_write_tool import create_file_write_tool
from myrm_agent_harness.agent.sub_agents.builder import filter_tools
from myrm_agent_harness.agent.sub_agents.manager import SubagentManager
from myrm_agent_harness.agent.sub_agents.spawn_capability import derive_spawn_capability
from myrm_agent_harness.agent.sub_agents.spawn_prep import apply_readonly_to_config
from myrm_agent_harness.agent.sub_agents.types import SubagentConfig, SubAgentResult, SubAgentStatus
from myrm_agent_harness.agent.types import WorkspaceBinding
from myrm_agent_harness.core.security.ocap import (
    AttenuationError,
    CapabilityAction,
    CapabilityHandle,
    capability_scope,
    check_capability_access,
    get_current_capability,
)
from myrm_agent_harness.toolkits.code_execution import create_executor

_FILE_CONTENT = "written by the child"
_HOUR_SECONDS = 3600.0


class _ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, tools: object, **kwargs: object) -> _ScriptedModel:
        return self


def _write_script(filename: str) -> list[BaseMessage]:
    call = {"name": "file_write_tool", "args": {"path": filename, "content": _FILE_CONTENT}, "id": "call_1"}
    return [AIMessage(content="", tool_calls=[call]), AIMessage(content="finished")]


def _mint_handle(workspace_path: str, *, readonly: bool) -> CapabilityHandle:
    """Mint the way delegate_task_tool does: scope comes from the parent's workspace path."""
    return derive_spawn_capability(
        parent_agent=SimpleNamespace(_last_context={"workspace_path": workspace_path}),
        agent_type="coding",
        readonly=readonly,
    )


async def _run_child(*, root: str, storage_root: Path, filename: str, readonly: bool) -> str:
    """Run one scripted child under a freshly minted handle; return the stringified event stream."""
    agent = BaseAgent(
        llm=_ScriptedModel(responses=_write_script(filename)),
        executor=create_executor(),
        tools=[create_file_write_tool()],
    )
    run_context: dict[str, object] = {
        "workspaces_storage_root": str(storage_root),
        "session_id": "chat_spawn_capability",
        "workspace_binding": WorkspaceBinding(mode="chat", root_path=root, chat_id="spawn_capability"),
        "workspace_path": root,
    }
    events: list[str] = []
    with capability_scope(_mint_handle(root, readonly=readonly)):
        async for event in agent.run("write the file", context=run_context):
            events.append(str(event))
    return "\n".join(events)


@pytest.fixture
def storage_root(tmp_path: Path) -> Path:
    storage = (tmp_path / "storage").resolve()
    storage.mkdir()
    return storage


@pytest.fixture
def project(tmp_path: Path) -> tuple[Path, Path]:
    """A real project directory and a symlink to it, both under the resolved tmp root."""
    real_root = (tmp_path / "real_project").resolve()
    real_root.mkdir()
    link_root = tmp_path.resolve() / "linked_project"
    if sys.platform != "win32":
        link_root.symlink_to(real_root, target_is_directory=True)
    return real_root, link_root


@pytest.mark.skipif(sys.platform == "win32", reason="symlink creation needs privileges on Windows")
@pytest.mark.parametrize("via_symlink", [False, True], ids=["plain_root", "symlinked_root"])
async def test_writable_child_can_write_under_declared_workspace_root(
    via_symlink: bool, project: tuple[Path, Path], storage_root: Path
) -> None:
    real_root, link_root = project
    declared_root = str(link_root if via_symlink else real_root)

    await _run_child(root=declared_root, storage_root=storage_root, filename="out.txt", readonly=False)

    assert (real_root / "out.txt").read_text(encoding="utf-8") == _FILE_CONTENT


async def test_readonly_child_cannot_write(project: tuple[Path, Path], storage_root: Path) -> None:
    real_root, _ = project

    events = await _run_child(root=str(real_root), storage_root=storage_root, filename="out.txt", readonly=True)

    assert not (real_root / "out.txt").exists()
    assert "denied by capability" in events


async def test_spawn_made_inside_a_child_run_is_bounded_by_the_childs_handle(
    project: tuple[Path, Path], storage_root: Path
) -> None:
    """A child's own `delegate_task` derives from the handle its run is bound to, so a read-only child cannot spawn a writer."""
    real_root, _ = project
    outcomes: list[str] = []

    async def spawn_attempt() -> str:
        try:
            derive_spawn_capability(parent_agent=agent, agent_type="grandchild", readonly=False)
        except AttenuationError:
            outcomes.append("denied")
        else:
            outcomes.append("minted")
        return "attempted"

    probe = StructuredTool.from_function(
        coroutine=spawn_attempt, name="file_read_tool", description="Stands in for the child's delegate_task call."
    )
    call = {"name": "file_read_tool", "args": {}, "id": "call_1"}
    agent = BaseAgent(
        llm=_ScriptedModel(responses=[AIMessage(content="", tool_calls=[call]), AIMessage(content="finished")]),
        executor=create_executor(),
        tools=[probe],
    )
    run_context: dict[str, object] = {
        "workspaces_storage_root": str(storage_root),
        "session_id": "chat_spawn_capability",
        "workspace_binding": WorkspaceBinding(mode="chat", root_path=str(real_root), chat_id="spawn_capability"),
        "workspace_path": str(real_root),
    }

    with capability_scope(_mint_handle(str(real_root), readonly=True)):
        async for _ in agent.run("delegate something", context=run_context):
            pass

    assert outcomes == ["denied"]


async def test_bound_handle_is_not_copied_into_the_childs_runtime_context(
    project: tuple[Path, Path], storage_root: Path
) -> None:
    """The runtime context is forwarded and persisted as plain data; the handle lives only in the capability scope."""
    real_root, _ = project
    agent = BaseAgent(llm=_ScriptedModel(responses=[AIMessage(content="finished")]), executor=create_executor())
    run_context: dict[str, object] = {
        "workspaces_storage_root": str(storage_root),
        "session_id": "chat_spawn_capability",
        "workspace_binding": WorkspaceBinding(mode="chat", root_path=str(real_root), chat_id="spawn_capability"),
        "workspace_path": str(real_root),
    }

    with capability_scope(_mint_handle(str(real_root), readonly=False)):
        async for _ in agent.run("say hi", context=run_context):
            pass

    assert agent._last_context is not None
    assert not any(isinstance(value, CapabilityHandle) for value in agent._last_context.values())


def test_spawn_handle_outlives_any_single_attempt_and_is_bounded() -> None:
    handle = _mint_handle("/tmp/workspace", readonly=False)
    assert not handle.is_expired(handle.issued_at + _HOUR_SECONDS)
    assert handle.is_expired(handle.issued_at + 25 * _HOUR_SECONDS)


@pytest.mark.skipif(sys.platform == "win32", reason="symlink creation needs privileges on Windows")
def test_handle_covers_the_path_forms_each_executor_presents(project: tuple[Path, Path], tmp_path: Path) -> None:
    """The file tools present symlink-resolved paths; the shell executor presents the bound (unresolved) cwd."""
    real_root, link_root = project
    outside = (tmp_path / "outside").resolve()
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    (real_root / "leak").symlink_to(outside, target_is_directory=True)
    (tmp_path / "real_project_evil").mkdir()
    handle = _mint_handle(str(link_root), readonly=False)

    def allowed(action: CapabilityAction, target: Path) -> bool:
        return check_capability_access(action, str(target), handle=handle)

    assert allowed(CapabilityAction.EXECUTE, link_root)
    assert allowed(CapabilityAction.EXECUTE, link_root / "sub")
    assert allowed(CapabilityAction.WRITE, real_root / "new.txt")
    assert allowed(CapabilityAction.READ, link_root / "new.txt")
    assert not allowed(CapabilityAction.WRITE, outside / "secret.txt")
    assert not allowed(CapabilityAction.WRITE, real_root / "leak" / "secret.txt")
    assert not allowed(CapabilityAction.WRITE, link_root / "leak" / "secret.txt")
    assert not allowed(CapabilityAction.WRITE, tmp_path / "real_project_evil" / "x.txt")


def _real_tool_names() -> dict[str, BaseTool]:
    tools = [
        create_file_write_tool(),
        create_file_edit_tool(),
        create_bash_code_execute_tool(),
        create_file_read_tool(),
    ]
    return {tool.name: tool for tool in tools}


def test_readonly_config_blocks_every_native_workspace_mutator() -> None:
    parent_tools = _real_tool_names()
    readonly_config = apply_readonly_to_config(SubagentConfig(system_prompt="explorer"), True)

    kept = {tool.name for tool in filter_tools(readonly_config, list(parent_tools.values()))}

    assert kept == {"file_read_tool"}


async def test_detached_child_keeps_its_handle_after_the_spawn_scope_exits(tmp_path: Path) -> None:
    """A `wait=False` child outlives the `capability_scope` that spawned it and must still run under that handle."""
    parent = MagicMock()
    parent.trigger_async_wakeup = AsyncMock()
    with patch("myrm_agent_harness.agent.hooks.graceful_shutdown.get_shutdown_manager", return_value=MagicMock()):
        manager = SubagentManager(parent_agent=parent)
    seen: list[CapabilityHandle | None] = []

    async def run_subagent(*, task_id: str, agent_type: str, **_: object) -> SubAgentResult:
        await asyncio.sleep(0)
        seen.append(get_current_capability())
        return SubAgentResult(
            success=True,
            task_id=task_id,
            agent_type=agent_type,
            result="done",
            completed_at=time.time(),
            status=SubAgentStatus.COMPLETED,
        )

    handle = _mint_handle(str(tmp_path), readonly=True)
    with patch.object(manager, "_run_subagent", run_subagent), capability_scope(handle):
        await manager.spawn_child(
            task_id="detached_1",
            agent_type="explorer",
            task_description="inspect",
            config=SubagentConfig(system_prompt="explorer"),
            context={},
            tool_registry_getter=list,
            wait=False,
            internal=True,
        )

    assert get_current_capability() is None
    await asyncio.gather(*manager.children.values())
    assert seen == [handle]
