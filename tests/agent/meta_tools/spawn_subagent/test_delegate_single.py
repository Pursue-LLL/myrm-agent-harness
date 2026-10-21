"""Single-mode delegation: the router-to-executor parameter contract and the approval pause/resume loop."""

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.errors import GraphInterrupt

from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_input import DelegateTaskInput
from myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_single import (
    _approval_interrupt_payload,
    _compose_task,
    execute_single_delegation,
)
from myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool import create_delegate_task_tool
from myrm_agent_harness.agent.sub_agents.approval_journal import ApprovalJournal
from myrm_agent_harness.agent.sub_agents.types import SubagentConfig, SubAgentResult, SubAgentStatus

_BASH = "bash_code_execute_tool"
_SINGLE = "myrm_agent_harness.agent.meta_tools.spawn_subagent._delegate_single"
_OTHER_MODE_FIELDS = frozenset(
    {
        "mode",
        "tasks",
        "race",
        "tournament",
        "judge_criteria",
        "max_concurrent",
        "expert_agent_types",
        "cross_review_rounds",
        "chair_agent_type",
    }
)
_SINGLE_MODE_FIELDS = frozenset(DelegateTaskInput.model_fields) - _OTHER_MODE_FIELDS
_ROUTER_CONTEXT = frozenset({"parent_agent", "tool_registry_getter", "catalog", "parent_type", "allowed_types"})
# Preset identifiers the product ships in app/config/subagents/core/*.yaml, and an English and a Chinese objective.
_SHIPPED_AGENT_TYPES = ("coding", "search", "explore", "analysis", "browser", "deep-audit")
_OBJECTIVES = (
    "Fix the failing unit test in the authentication module",
    "调研本周 AI Agent 领域的最新进展并整理成报告",
)


def _parent() -> MagicMock:
    parent = MagicMock()
    parent._last_context = {"session_id": "s1"}
    parent._subagent_manager = MagicMock(current_depth=0, approval_journal=ApprovalJournal())
    return parent


def _catalog() -> AsyncMock:
    catalog = AsyncMock()
    catalog.resolve = AsyncMock(return_value=SubagentConfig(system_prompt="You are a mock agent", tools=(_BASH,)))
    return catalog


def _result(status: SubAgentStatus, payload: dict[str, object] | None = None) -> SubAgentResult:
    return SubAgentResult(
        success=status == SubAgentStatus.COMPLETED,
        task_id="child",
        agent_type="coder",
        result="Done",
        completed_at=1.0,
        status=status,
        payload=payload,
    )


def test_task_text_appends_the_file_list_and_the_json_context() -> None:
    task = _compose_task("Fix it", ["a.py", "b.py"], {"k": "v"})

    assert task.startswith("Fix it\n\nRelevant files/resources:\n- a.py\n- b.py")
    assert '```json\n{\n  "k": "v"\n}\n```' in task


def test_task_text_falls_back_to_the_plain_repr_for_an_unserializable_context() -> None:
    context = {"handle": object()}

    assert _compose_task("Fix it", None, context) == f"Fix it\n\nAdditional Context Data:\n{context!s}"


def test_router_accepts_exactly_the_schema_fields() -> None:
    tool = create_delegate_task_tool(_parent(), list, _catalog())

    assert set(inspect.signature(tool.coroutine).parameters) == set(DelegateTaskInput.model_fields)


def test_executor_takes_exactly_the_single_mode_fields_and_the_router_context() -> None:
    assert set(inspect.signature(execute_single_delegation).parameters) == _SINGLE_MODE_FIELDS | _ROUTER_CONTEXT


@pytest.mark.asyncio
async def test_router_forwards_every_single_mode_field_untouched() -> None:
    tool = create_delegate_task_tool(_parent(), list, _catalog())
    values = {name: object() for name in _SINGLE_MODE_FIELDS}

    with patch(
        "myrm_agent_harness.agent.meta_tools.spawn_subagent.delegate_task_tool.execute_single_delegation",
        new=AsyncMock(return_value={"success": True}),
    ) as executor:
        await tool.coroutine(**values)

    forwarded = executor.call_args.kwargs
    assert {name: forwarded[name] for name in _SINGLE_MODE_FIELDS} == values
    assert set(forwarded) == _SINGLE_MODE_FIELDS | _ROUTER_CONTEXT


def test_approval_payload_lists_each_request_with_its_command_span_details() -> None:
    pending = _result(
        SubAgentStatus.PENDING_APPROVAL,
        {
            "extra": 1,
            "actionRequests": [
                {
                    "action": _BASH,
                    "args": {"command": "rm x"},
                    "command_spans": [[0, 4]],
                    "command_span_risks": ["high"],
                    "command_span_reasons": ["deletes a file"],
                },
                {"action": "file_write_tool", "args": {"path": "a"}, "command_spans": []},
                {"args": "not-a-dict"},
                "not-a-request",
            ],
        },
    )

    payload = _approval_interrupt_payload("t1", pending)

    assert payload["subagent_task_id"] == "t1"
    assert payload["extra"] == 1
    assert payload["tool_calls"] == [
        {
            "name": _BASH,
            "args": {
                "command": "rm x",
                "command_spans": [[0, 4]],
                "command_span_risks": ["high"],
                "command_span_reasons": ["deletes a file"],
            },
        },
        {"name": "file_write_tool", "args": {"path": "a"}},
        {"name": "unknown", "args": {}},
    ]


def test_approval_payload_has_no_tool_calls_when_the_requests_are_unusable() -> None:
    payload = _approval_interrupt_payload("t1", _result(SubAgentStatus.PENDING_APPROVAL, {"actionRequests": "bad"}))

    assert "tool_calls" not in payload


def test_approval_payload_passes_a_missing_payload_through() -> None:
    payload = _approval_interrupt_payload("t1", _result(SubAgentStatus.PENDING_APPROVAL))

    assert payload == {"action_type": "subagent_approval", "subagent_task_id": "t1", "payload": None}


@pytest.mark.asyncio
async def test_pending_approval_resumes_the_same_spawn_with_the_ui_decision() -> None:
    parent = _parent()
    pending = _result(
        SubAgentStatus.PENDING_APPROVAL,
        {"actionRequests": [{"action": _BASH, "args": {"command": "ls"}}]},
    )
    parent._spawn_child = AsyncMock(side_effect=[pending, _result(SubAgentStatus.COMPLETED)])
    tool = create_delegate_task_tool(parent, list, _catalog())
    decisions = {"decisions": [{"type": "approve"}]}

    # LangGraph runs the call again once the user answers; outside a graph the delegation id is random, so pin it.
    with (
        patch(f"{_SINGLE}.delegation_task_id", return_value="t1"),
        patch("langgraph.types.interrupt", side_effect=[GraphInterrupt(), decisions]) as interrupt,
    ):
        with pytest.raises(GraphInterrupt):
            await tool.coroutine(agent_type="coder", objective="Write a function", wait=True)
        result = await tool.coroutine(agent_type="coder", objective="Write a function", wait=True)

    assert result["success"] is True
    (payload,) = interrupt.call_args.args
    assert payload["action_type"] == "subagent_approval"
    assert payload["tool_calls"] == [{"name": _BASH, "args": {"command": "ls"}}]
    first, resumed = parent._spawn_child.call_args_list
    assert payload["subagent_task_id"] == first.kwargs["task_id"]
    assert "resume_command" not in first.kwargs
    assert resumed.kwargs.pop("resume_command").resume == decisions
    assert resumed.kwargs == first.kwargs


@pytest.mark.asyncio
@pytest.mark.parametrize("objective", _OBJECTIVES)
@pytest.mark.parametrize("agent_type", _SHIPPED_AGENT_TYPES)
async def test_an_explicit_shipped_agent_type_is_spawned_as_named(agent_type: str, objective: str) -> None:
    parent = _parent()
    parent._spawn_child = AsyncMock(return_value=_result(SubAgentStatus.COMPLETED))
    catalog = _catalog()
    tool = create_delegate_task_tool(parent, list, catalog)

    result = await tool.coroutine(agent_type=agent_type, objective=objective, wait=True)

    assert result["success"] is True
    catalog.resolve.assert_awaited_once_with(agent_type)
    assert parent._spawn_child.call_args.kwargs["agent_type"] == agent_type


@pytest.mark.asyncio
async def test_an_agent_type_missing_from_the_catalog_is_reported_without_spawning() -> None:
    parent = _parent()
    parent._spawn_child = AsyncMock()
    catalog = _catalog()
    catalog.resolve = AsyncMock(return_value=None)
    tool = create_delegate_task_tool(parent, list, catalog)

    result = await tool.coroutine(agent_type="no-such-agent", objective="Summarise the open issues", wait=True)

    assert result["success"] is False
    assert "'no-such-agent' not found in catalog" in result["error"]
    parent._spawn_child.assert_not_awaited()


@pytest.mark.asyncio
async def test_single_mode_without_an_agent_type_is_rejected_without_spawning() -> None:
    parent = _parent()
    parent._spawn_child = AsyncMock()
    tool = create_delegate_task_tool(parent, list, _catalog())

    result = await tool.coroutine(objective="Summarise the open issues", wait=True)

    assert result["success"] is False
    assert "agent_type and objective are required" in result["error"]
    parent._spawn_child.assert_not_awaited()
