"""delegate_task verification routing: verifier choice, fallback and refusal of a verifier that cannot run commands."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.tools import StructuredTool

from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import create_delegate_task_tool
from myrm_agent_harness.agent.sub_agents.types import SubagentConfig, SubAgentResult, SubAgentStatus

_BASH = "bash_code_execute_tool"


def _noop() -> str:
    return ""


def _parent_tools(*names: str):
    return [StructuredTool.from_function(func=_noop, name=name, description=name) for name in names or (_BASH,)]


def _make_mock_parent():
    parent = MagicMock()
    parent.config = MagicMock()
    parent._manager = AsyncMock()
    parent._spawn_child = AsyncMock()
    return parent


def _make_mock_config(*tools: str):
    return SubagentConfig(
        system_prompt="You are a mock agent",
        tools=tools or (_BASH,),
    )


@pytest.mark.asyncio
async def test_delegate_task_with_verifier_prompt_and_wait_false():
    parent = _make_mock_parent()
    catalog = AsyncMock()
    tool = create_delegate_task_tool(parent, lambda: [], catalog)

    result = await tool.coroutine(
        agent_type="coder",
        objective="Write a function",
        wait=False,
        verifier_prompt="Verify it",
    )

    assert result["success"] is False
    assert "Adversarial verification requires wait=True" in result["error"]


@pytest.mark.asyncio
# The delegation path imports the verifier lazily at call time, so the patch has to
# land on the module object it resolves at that moment (the lazily imported attribute).
@patch("myrm_agent_harness.agent.sub_agents.orchestrator.run_with_verification")
async def test_delegate_task_with_verifier_prompt_and_wait_true(mock_run_with_verification):
    parent = _make_mock_parent()
    catalog = AsyncMock()
    catalog.resolve = AsyncMock(return_value=_make_mock_config())

    tool = create_delegate_task_tool(parent, _parent_tools, catalog)

    mock_result = SubAgentResult(
        success=True,
        task_id="test-task",
        agent_type="coder",
        result="Done",
        completed_at=123.0,
        status=SubAgentStatus.COMPLETED,
    )
    mock_run_with_verification.return_value = mock_result

    result = await tool.coroutine(
        agent_type="coder",
        objective="Write a function",
        wait=True,
        verifier_prompt="Verify it",
        verifier_agent_type="verifier",
        max_verification_rounds=3,
    )

    assert catalog.resolve.called
    mock_run_with_verification.assert_called_once()
    kwargs = mock_run_with_verification.call_args.kwargs
    assert kwargs["worker_type"] == "coder"
    assert kwargs["verifier_type"] == "verifier"
    assert kwargs["max_rounds"] == 3
    assert kwargs["verifier_task_template"] == "Verify it"
    assert result["success"] is True
    assert result["task_id"] == "test-task"


@pytest.mark.asyncio
# The delegation path imports the verifier lazily at call time, so the patch has to
# land on the module object it resolves at that moment (the lazily imported attribute).
@patch("myrm_agent_harness.agent.sub_agents.orchestrator.run_with_verification")
async def test_delegate_task_with_verifier_prompt_fallback_type(mock_run_with_verification):
    parent = _make_mock_parent()
    catalog = AsyncMock()

    def mock_resolve(type_id):
        if type_id == "coder":
            return _make_mock_config()
        return None

    catalog.resolve = AsyncMock(side_effect=mock_resolve)

    tool = create_delegate_task_tool(parent, _parent_tools, catalog)

    mock_result = SubAgentResult(
        success=True,
        task_id="test-task",
        agent_type="coder",
        result="Done",
        completed_at=123.0,
        status=SubAgentStatus.COMPLETED,
    )
    mock_run_with_verification.return_value = mock_result

    await tool.coroutine(
        agent_type="coder",
        objective="Write a function",
        wait=True,
        verifier_prompt="Verify it",
        verifier_agent_type="unknown-verifier",
        readonly=True,
    )

    assert catalog.resolve.called
    mock_run_with_verification.assert_called_once()
    kwargs = mock_run_with_verification.call_args.kwargs
    assert kwargs["verifier_type"] == "coder"
    # The worker is read-only, but the fallback verifier keeps the command tool it needs to run its checks.
    assert _BASH in kwargs["worker_config"].disallowed_tools
    assert _BASH not in kwargs["verifier_config"].disallowed_tools


@pytest.mark.asyncio
# The delegation path imports the verifier lazily at call time, so the patch has to
# land on the module object it resolves at that moment (the lazily imported attribute).
@patch("myrm_agent_harness.agent.sub_agents.orchestrator.run_with_verification")
async def test_delegate_task_refuses_a_verifier_that_cannot_run_commands(mock_run_with_verification):
    parent = _make_mock_parent()
    catalog = AsyncMock()
    catalog.resolve = AsyncMock(return_value=_make_mock_config("web_search_tool"))

    tool = create_delegate_task_tool(parent, lambda: _parent_tools(_BASH, "web_search_tool"), catalog)

    result = await tool.coroutine(
        agent_type="coder",
        objective="Write a function",
        wait=True,
        verifier_prompt="Verify it",
        verifier_agent_type="verifier",
    )

    assert result["success"] is False
    assert "cannot run commands" in result["error"]
    assert result["task_id"]
    mock_run_with_verification.assert_not_called()
    parent._spawn_child.assert_not_called()


@pytest.mark.asyncio
# The delegation path imports the verifier lazily at call time, so the patch has to
# land on the module object it resolves at that moment (the lazily imported attribute).
@patch("myrm_agent_harness.agent.sub_agents.orchestrator.run_with_verification")
async def test_corrected_verifier_retry_is_not_rejected_as_a_repeated_delegation(mock_run_with_verification):
    parent = _make_mock_parent()
    # A non-empty context is what makes the repeated-delegation history persist across calls.
    parent._last_context = {"session_id": "s1"}
    configs = {"coder": _make_mock_config(), "searcher": _make_mock_config("web_search_tool")}
    catalog = AsyncMock()
    catalog.resolve = AsyncMock(side_effect=configs.get)
    mock_run_with_verification.return_value = SubAgentResult(
        success=True,
        task_id="test-task",
        agent_type="coder",
        result="Done",
        completed_at=123.0,
        status=SubAgentStatus.COMPLETED,
    )

    tool = create_delegate_task_tool(parent, lambda: _parent_tools(_BASH, "web_search_tool"), catalog)
    call = {"agent_type": "coder", "objective": "Write a function", "wait": True, "verifier_prompt": "Verify it"}

    refused = await tool.coroutine(**call, verifier_agent_type="searcher")
    retried = await tool.coroutine(**call, verifier_agent_type="coder")

    assert "cannot run commands" in refused["error"]
    assert retried["success"] is True
    mock_run_with_verification.assert_called_once()


def _completed() -> SubAgentResult:
    return SubAgentResult(
        success=True,
        task_id="test-task",
        agent_type="coder",
        result="Done",
        completed_at=123.0,
        status=SubAgentStatus.COMPLETED,
    )


def _delegating_parent(*, remembers_history: bool):
    parent = _make_mock_parent()
    parent._spawn_child.return_value = _completed()
    if remembers_history:
        # A non-empty context is what makes the repeated-delegation history persist across calls.
        parent._last_context = {"session_id": "s1"}
    return parent


def _open_catalog() -> AsyncMock:
    catalog = AsyncMock()
    catalog.resolve = AsyncMock(return_value=_make_mock_config())
    return catalog


@pytest.mark.asyncio
# The delegation path imports the verifier lazily at call time, so the patch has to
# land on the module object it resolves at that moment (the lazily imported attribute).
@patch("myrm_agent_harness.agent.sub_agents.orchestrator.run_with_verification")
async def test_verified_delegation_is_not_answered_by_an_earlier_unverified_run(mock_run_with_verification):
    mock_run_with_verification.return_value = _completed()
    parent = _delegating_parent(remembers_history=False)
    tool = create_delegate_task_tool(parent, _parent_tools, _open_catalog())
    call = {"agent_type": "coder", "objective": "Ship the migration", "wait": True}

    await tool.coroutine(**call)
    verified = await tool.coroutine(**call, verifier_prompt="Verify it")

    assert verified["success"] is True
    assert "cached" not in verified
    mock_run_with_verification.assert_called_once()


_VERIFIED = {"verifier_prompt": "Verify it"}


@pytest.mark.asyncio
# The delegation path imports the verifier lazily at call time, so the patch has to
# land on the module object it resolves at that moment (the lazily imported attribute).
@patch("myrm_agent_harness.agent.sub_agents.orchestrator.run_with_verification")
@pytest.mark.parametrize(
    ("first", "second"),
    [
        ({}, {"readonly": True}),
        ({}, {"complexity_tier": "reasoning"}),
        ({}, _VERIFIED),
        (_VERIFIED, {**_VERIFIED, "verifier_agent_type": "coder"}),
        (_VERIFIED, {**_VERIFIED, "max_verification_rounds": 3}),
    ],
    ids=["readonly", "complexity_tier", "verifier_prompt", "verifier_agent_type", "max_verification_rounds"],
)
async def test_delegations_differing_in_how_they_run_are_not_repeats(mock_run_with_verification, first, second):
    mock_run_with_verification.return_value = _completed()
    parent = _delegating_parent(remembers_history=True)
    tool = create_delegate_task_tool(parent, _parent_tools, _open_catalog())
    call = {"agent_type": "coder", "objective": "Ship the migration", "wait": True}

    await tool.coroutine(**call, **first)
    result = await tool.coroutine(**call, **second)

    assert result["task_id"] != "deadlock-prevented"
    assert result["success"] is True


@pytest.mark.asyncio
async def test_delegation_survives_a_lone_surrogate_in_the_objective():
    tool = create_delegate_task_tool(_delegating_parent(remembers_history=False), _parent_tools, _open_catalog())

    result = await tool.coroutine(agent_type="coder", objective="fix \ud800 bug", wait=True)

    assert result["success"] is True
