"""A verifier's read-only boundary and execution evidence, driven through the real child-run chain.

A scripted model issues real tool calls inside a real `BaseAgent.run`, which performs the production
tool interceptor, file executor and shell executor. Only the model is scripted. The verifier's handle
is minted by the production `derive_verifier_capability` and bound by `capability_scope`, exactly as the
verifier round does.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.base_agent import BaseAgent
from myrm_agent_harness.agent.meta_tools.bash.bash_code_execute_tool import create_bash_code_execute_tool
from myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool import create_file_read_tool
from myrm_agent_harness.agent.meta_tools.file_ops.file_write_tool import create_file_write_tool
from myrm_agent_harness.agent.sub_agents.spawn_capability import derive_spawn_capability, derive_verifier_capability
from myrm_agent_harness.agent.types import AgentRuntimeConfig, WorkspaceBinding
from myrm_agent_harness.core.security.ocap import CapabilityHandle, capability_scope
from myrm_agent_harness.core.security.types import PermissionAction, PermissionRule, SecurityConfig
from myrm_agent_harness.toolkits.code_execution import create_executor
from myrm_agent_harness.toolkits.code_execution.executors.execution_evidence import track_execution
from myrm_agent_harness.toolkits.code_execution.sandbox import detect_sandbox_provider

_requires_os_sandbox = pytest.mark.skipif(
    not detect_sandbox_provider()[1].enabled, reason="OS-level workspace read-only needs a sandbox provider"
)


class _ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, tools: object, **kwargs: object) -> _ScriptedModel:
        return self


def _tool_script(tool_name: str, args: dict[str, object]) -> list[BaseMessage]:
    call = {"name": tool_name, "args": args, "id": "call_1"}
    return [AIMessage(content="", tool_calls=[call]), AIMessage(content="finished")]


def _approving_security(workspace: Path) -> SecurityConfig:
    """Workspace profile that approves every tool call, so only the capability layer decides the outcome."""
    base = SecurityConfig.workspace(allowed_roots=(str(workspace),))
    return replace(base, ruleset=(*base.ruleset, PermissionRule("*", "*", PermissionAction.ALLOW)))


def _writer_handle(workspace: str) -> CapabilityHandle:
    return derive_spawn_capability(
        parent_agent=SimpleNamespace(_last_context={"workspace_path": workspace}),
        agent_type="worker",
        readonly=False,
    )


async def _run_verifier(
    *, root: Path, storage_root: Path, tool: BaseTool, script: list[BaseMessage]
) -> tuple[str, bool]:
    """Run a scripted verifier under the handle the verifier round derives from the worker's handle.

    Returns the stringified event stream and whether the run launched a process.
    """
    agent = BaseAgent(
        llm=_ScriptedModel(responses=script),
        executor=create_executor(),
        tools=[tool],
        config=AgentRuntimeConfig(security_config=_approving_security(root)),
    )
    run_context: dict[str, object] = {
        "workspaces_storage_root": str(storage_root),
        "session_id": "chat_verifier_capability",
        "workspace_binding": WorkspaceBinding(mode="chat", root_path=str(root), chat_id="verifier_capability"),
        "workspace_path": str(root),
    }
    events: list[str] = []
    with capability_scope(_writer_handle(str(root))):
        verifier_handle = derive_verifier_capability("adversarial-reviewer")
        with track_execution() as evidence, capability_scope(verifier_handle):
            async for event in agent.run("verify the work", context=run_context):
                events.append(str(event))
    return "\n".join(events), evidence.executed


@pytest.fixture
def storage_root(tmp_path: Path) -> Path:
    storage = (tmp_path / "storage").resolve()
    storage.mkdir()
    return storage


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = (tmp_path / "project").resolve()
    root.mkdir()
    (root / "report.txt").write_text("worker output", encoding="utf-8")
    return root


async def test_verifier_cannot_write_through_the_file_tool(workspace: Path, storage_root: Path) -> None:
    script = _tool_script("file_write_tool", {"path": "evil.txt", "content": "tamper"})

    events, executed = await _run_verifier(
        root=workspace, storage_root=storage_root, tool=create_file_write_tool(), script=script
    )

    assert not (workspace / "evil.txt").exists()
    assert "denied by capability" in events
    assert executed is False


async def test_verifier_reading_a_file_is_allowed_and_is_not_execution_evidence(
    workspace: Path, storage_root: Path
) -> None:
    script = _tool_script("file_read_tool", {"paths": ["report.txt"]})

    events, executed = await _run_verifier(
        root=workspace, storage_root=storage_root, tool=create_file_read_tool(), script=script
    )

    assert "'action_type': 'read'" in events
    assert "denied by capability" not in events
    assert executed is False


async def test_verifier_shell_command_is_execution_evidence(workspace: Path, storage_root: Path) -> None:
    script = _tool_script("bash_code_execute_tool", {"reason": "verify the output", "command": "cat report.txt"})

    events, executed = await _run_verifier(
        root=workspace, storage_root=storage_root, tool=create_bash_code_execute_tool(), script=script
    )

    assert "worker output" in events
    assert executed is True


@_requires_os_sandbox
@pytest.mark.parametrize("command", ["echo tamper > report.txt", "touch created.txt"], ids=["overwrite", "create"])
async def test_verifier_shell_cannot_modify_the_workspace(command: str, workspace: Path, storage_root: Path) -> None:
    script = _tool_script("bash_code_execute_tool", {"reason": "verify the output", "command": command})

    _, executed = await _run_verifier(
        root=workspace, storage_root=storage_root, tool=create_bash_code_execute_tool(), script=script
    )

    assert not (workspace / "created.txt").exists()
    assert (workspace / "report.txt").read_text(encoding="utf-8") == "worker output"
    assert executed is True


@_requires_os_sandbox
async def test_verifier_shell_can_keep_scratch_output_outside_the_workspace(
    workspace: Path, storage_root: Path, tmp_path: Path
) -> None:
    scratch = Path("/tmp") / f"verifier_scratch_{tmp_path.name}.txt"
    script = _tool_script(
        "bash_code_execute_tool",
        {"reason": "verify the output", "command": f"cat report.txt > {scratch} && cat {scratch}"},
    )

    try:
        events, _ = await _run_verifier(
            root=workspace, storage_root=storage_root, tool=create_bash_code_execute_tool(), script=script
        )
        assert scratch.read_text(encoding="utf-8") == "worker output"
        assert "worker output" in events
    finally:
        scratch.unlink(missing_ok=True)


@_requires_os_sandbox
async def test_verifier_background_job_cannot_modify_the_workspace(
    workspace: Path, storage_root: Path, tmp_path: Path
) -> None:
    denied_marker = Path("/tmp") / f"verifier_bg_denied_{tmp_path.name}"
    script = _tool_script(
        "bash_code_execute_tool",
        {
            "reason": "verify the output",
            "command": f"echo tamper > created.txt || echo denied > {denied_marker}",
            "run_in_background": True,
        },
    )

    try:
        _, executed = await _run_verifier(
            root=workspace, storage_root=storage_root, tool=create_bash_code_execute_tool(), script=script
        )
        for _ in range(100):
            if denied_marker.exists():
                break
            await asyncio.sleep(0.1)
        assert denied_marker.exists(), "the background job never reported the denied write"
        assert not (workspace / "created.txt").exists()
        assert executed is True
    finally:
        denied_marker.unlink(missing_ok=True)
