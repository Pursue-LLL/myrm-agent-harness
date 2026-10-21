"""Focused tests for _verifier_round: verdict delivery, capability scoping and the execution-evidence gate."""

from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.tools import BaseTool, StructuredTool

from myrm_agent_harness.agent.sub_agents._verification_parsing import VerificationVerdict
from myrm_agent_harness.agent.sub_agents._verifier_round import (
    _build_verifier_tool_registry_getter,
    verify_worker_output,
)
from myrm_agent_harness.agent.sub_agents.builder import filter_tools
from myrm_agent_harness.agent.sub_agents.spawn_capability import derive_spawn_capability
from myrm_agent_harness.agent.sub_agents.types import SubagentConfig, SubAgentResult, SubAgentStatus, WorkspacePolicy
from myrm_agent_harness.core.security.ocap import (
    CapabilityAction,
    CapabilityHandle,
    capability_scope,
    get_current_capability,
)
from myrm_agent_harness.toolkits.code_execution.executors.execution_evidence import record_execution


class _ParentTool:
    name = "file_read_tool"


def test_build_verifier_tool_registry_getter_adds_submit_verdict() -> None:
    context: dict[str, object] = {}
    getter = _build_verifier_tool_registry_getter(lambda: [_ParentTool()], context)
    tools = getter()
    tool_names = [getattr(t, "name", "") for t in tools]
    assert tool_names == ["file_read_tool", "submit_verdict"]

    submit = next(t for t in tools if getattr(t, "name", "") == "submit_verdict")
    submit.invoke(
        {
            "passed": True,
            "summary": "ok",
            "findings": [],
            "confidence": "HIGH",
        }
    )
    verdict = context.get("_verifier_verdict")
    assert isinstance(verdict, VerificationVerdict)
    assert verdict.passed is True


_VERIFIER_ACTIONS = frozenset({CapabilityAction.READ, CapabilityAction.EXECUTE})


def _read_only_config() -> SubagentConfig:
    return SubagentConfig(system_prompt="verifier", workspace_policy=WorkspacePolicy.READ_ONLY_SANDBOX)


def _verifier_spawn(
    *,
    passed: bool = True,
    ran_command: bool = True,
    summary: str = "Verified with evidence",
    seen_handles: list[CapabilityHandle | None] | None = None,
):
    """Fake ``spawn_child`` for a verifier.

    It submits its verdict through the real ``submit_verdict`` tool, the way a model does, and launches a
    command (the executor's evidence signal) only when ``ran_command`` is set.
    """

    async def _spawn(**kwargs) -> SubAgentResult:
        if seen_handles is not None:
            seen_handles.append(get_current_capability())
        if ran_command:
            record_execution()
        submit = next(t for t in kwargs["tool_registry_getter"]() if t.name == "submit_verdict")
        submit.invoke({"passed": passed, "summary": summary, "findings": [], "confidence": "HIGH"})
        return SubAgentResult(
            success=True,
            task_id=kwargs["task_id"],
            agent_type=kwargs["agent_type"],
            result="done",
            completed_at=0.0,
            status=SubAgentStatus.COMPLETED,
        )

    return _spawn


async def _verify(
    mgr: MagicMock,
    *,
    config: SubagentConfig,
    context: dict[str, object] | None = None,
    parent_tools: list[BaseTool] | None = None,
):
    return await verify_worker_output(
        mgr,
        worker_output="worker output",
        worker_type="worker",
        verifier_type="adversarial-reviewer",
        verifier_config=config,
        context={} if context is None else context,
        tool_registry_getter=lambda: parent_tools or [],
        verifier_task_template="Confirm output matches side effects.",
    )


def _writer_handle(workspace: str) -> CapabilityHandle:
    return derive_spawn_capability(
        parent_agent=SimpleNamespace(_last_context={"workspace_path": workspace}),
        agent_type="worker",
        readonly=False,
    )


@pytest.mark.asyncio
async def test_verify_worker_output_returns_tool_submitted_verdict() -> None:
    mgr = MagicMock()
    mgr.spawn_child = _verifier_spawn(ran_command=True)

    verdict = await _verify(mgr, config=_read_only_config())

    assert verdict is not None
    assert verdict.passed is True
    assert verdict.summary == "Verified with evidence"


def _parent_tool(name: str) -> BaseTool:
    return StructuredTool.from_function(func=lambda: name, name=name, description=f"Parent tool {name}")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("allowlist", "expected_tools"),
    [
        (("file_read_tool",), ["file_read_tool", "submit_verdict"]),
        ((), ["file_read_tool", "file_write_tool", "submit_verdict"]),
    ],
    ids=["preset-allowlist", "no-allowlist"],
)
async def test_verifier_keeps_its_verdict_channel_under_any_tool_allowlist(
    allowlist: tuple[str, ...], expected_tools: list[str]
) -> None:
    """The round provides ``submit_verdict`` itself: a preset allowlist must not strip it, and an empty
    allowlist must not turn into a one-tool allowlist that strips everything else."""
    exposed: list[str] = []

    async def _spawn(**kwargs) -> SubAgentResult:
        exposed.extend(t.name for t in filter_tools(kwargs["config"], kwargs["tool_registry_getter"]()))
        return SubAgentResult(
            success=True,
            task_id=kwargs["task_id"],
            agent_type=kwargs["agent_type"],
            result="done",
            completed_at=0.0,
            status=SubAgentStatus.COMPLETED,
        )

    mgr = MagicMock()
    mgr.spawn_child = _spawn
    config = replace(_read_only_config(), tools=allowlist)

    await _verify(mgr, config=config, parent_tools=[_parent_tool("file_read_tool"), _parent_tool("file_write_tool")])

    assert exposed == expected_tools


@pytest.mark.asyncio
async def test_pass_without_a_launched_command_is_inconclusive() -> None:
    mgr = MagicMock()
    mgr.spawn_child = _verifier_spawn(ran_command=False)

    verdict = await _verify(mgr, config=_read_only_config())

    assert verdict is None


@pytest.mark.asyncio
async def test_fail_verdict_is_not_altered_by_missing_execution() -> None:
    mgr = MagicMock()
    mgr.spawn_child = _verifier_spawn(passed=False, ran_command=False, summary="Output is wrong")

    verdict = await _verify(mgr, config=_read_only_config())

    assert verdict is not None
    assert verdict.passed is False
    assert verdict.summary == "Output is wrong"


@pytest.mark.asyncio
async def test_read_only_verifier_runs_under_read_execute_handle_and_releases_it() -> None:
    mgr = MagicMock()
    seen: list[CapabilityHandle | None] = []
    mgr.spawn_child = _verifier_spawn(seen_handles=seen)

    await _verify(mgr, config=_read_only_config())

    (handle,) = seen
    assert handle is not None
    assert handle.actions == _VERIFIER_ACTIONS
    assert get_current_capability() is None


@pytest.mark.asyncio
async def test_verifier_handle_is_attenuated_from_the_delegating_agents_handle(tmp_path) -> None:
    parent = _writer_handle(str(tmp_path))
    mgr = MagicMock()
    seen: list[CapabilityHandle | None] = []
    mgr.spawn_child = _verifier_spawn(seen_handles=seen)

    with capability_scope(parent):
        await _verify(mgr, config=_read_only_config())
        assert get_current_capability() is parent

    (handle,) = seen
    assert handle is not None
    assert CapabilityAction.WRITE in parent.actions
    assert handle.actions == _VERIFIER_ACTIONS
    assert handle.scope == parent.scope
    assert handle.issuer_id == parent.subject_id


@pytest.mark.asyncio
async def test_verifier_cannot_widen_a_read_only_parent(tmp_path) -> None:
    parent = derive_spawn_capability(
        parent_agent=SimpleNamespace(_last_context={"workspace_path": str(tmp_path)}),
        agent_type="explorer",
        readonly=True,
    )
    mgr = MagicMock()
    seen: list[CapabilityHandle | None] = []
    mgr.spawn_child = _verifier_spawn(seen_handles=seen)

    with capability_scope(parent):
        await _verify(mgr, config=_read_only_config())

    (handle,) = seen
    assert handle is not None
    assert handle.actions == parent.actions & _VERIFIER_ACTIONS


@pytest.mark.asyncio
async def test_expired_parent_handle_leaves_the_verification_inconclusive_without_spawning(tmp_path) -> None:
    expired = replace(_writer_handle(str(tmp_path)), expires_at=time.monotonic() - 1.0)
    mgr = MagicMock()
    mgr.spawn_child = AsyncMock()

    with capability_scope(expired):
        verdict = await _verify(mgr, config=_read_only_config())

    assert verdict is None
    mgr.spawn_child.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_read_only_verifier_keeps_the_callers_handle(tmp_path) -> None:
    parent = _writer_handle(str(tmp_path))
    mgr = MagicMock()
    seen: list[CapabilityHandle | None] = []
    mgr.spawn_child = _verifier_spawn(seen_handles=seen)

    with capability_scope(parent):
        await _verify(mgr, config=SubagentConfig(system_prompt="verifier"))

    assert seen == [parent]


@pytest.mark.asyncio
async def test_parallel_rounds_keep_their_own_verdict_and_evidence() -> None:
    """Skeptics run concurrently on one shared context; none may read another's verdict or evidence."""
    shared_context: dict[str, object] = {}
    mgr = MagicMock()

    async def _spawn(**kwargs) -> SubAgentResult:
        index = int(kwargs["agent_type"].rsplit("-", 1)[1])
        await asyncio.sleep(0.01 * (3 - index))  # finish in reverse order to expose cross-talk
        spawn = _verifier_spawn(passed=True, ran_command=index != 1, summary=f"skeptic {index}")
        return await spawn(**kwargs)

    mgr.spawn_child = _spawn

    verdicts = await asyncio.gather(
        *(
            verify_worker_output(
                mgr,
                worker_output="worker output",
                worker_type="worker",
                verifier_type=f"skeptic-{index}",
                verifier_config=_read_only_config(),
                context=shared_context,
                tool_registry_getter=lambda: [],
            )
            for index in range(3)
        )
    )

    first, lazy, last = verdicts
    assert lazy is None
    assert first is not None
    assert last is not None
    assert (first.passed, first.summary) == (True, "skeptic 0")
    assert (last.passed, last.summary) == (True, "skeptic 2")
    assert "_verifier_verdict" not in shared_context


@pytest.mark.asyncio
async def test_emit_verification_verdict_emits_when_sink_available() -> None:
    from myrm_agent_harness.agent.sub_agents._verification_parsing import _emit_verification_verdict

    sink = MagicMock()
    sink.emit = AsyncMock()
    verdict = VerificationVerdict(
        passed=False,
        summary="missing evidence",
        confidence="LOW",
        findings=[{"severity": "MAJOR", "description": "no tests run"}],
        raw="",
    )

    with patch(
        "myrm_agent_harness.utils.runtime.progress_sink.get_tool_progress_sink",
        return_value=sink,
    ):
        await _emit_verification_verdict(
            verdict=verdict,
            round_num=1,
            max_rounds=1,
            worker_type="worker",
            verifier_type="adversarial-reviewer",
            has_diff=True,
        )

    sink.emit.assert_awaited_once()
