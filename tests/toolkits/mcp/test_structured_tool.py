"""Unit tests for structured_tool.py — SafeStructuredTool reserved-name handling.

``langchain_core`` ``StructuredTool._run``/``_arun`` declare ``config``/
``run_manager`` as keyword-only parameters; a tool argument named ``config``
would be silently bound into that slot and dropped from the dispatched kwargs.
``SafeStructuredTool`` overrides both ``_run`` and ``_arun`` with a pure
``*args``/``**kwargs`` signature so every argument reaches the callable
verbatim — across async ``ainvoke``, sync ``invoke``, the ``run_in_executor``
fallback for coroutine-less tools, LangGraph ``ToolNode`` ToolCall-dict inputs,
real ``RunnableConfig`` co-existence, and Pydantic ``args_schema`` shapes.
These tests pin that behavior across value/missing/None/dot-path shapes.
"""

from __future__ import annotations

from typing import Any

import pytest

from myrm_agent_harness.toolkits.mcp import SafeStructuredTool


def _make_tool(
    coroutine: Any,
    props: dict[str, Any],
    required: list[str] | None = None,
) -> SafeStructuredTool:
    schema: dict[str, Any] = {"type": "object", "properties": props}
    if required:
        schema["required"] = required
    return SafeStructuredTool.from_function(
        func=lambda **kwargs: None,
        coroutine=coroutine,
        name="t",
        description="d",
        args_schema=schema,
    )


async def _echo(**kwargs: Any) -> str:
    return f"keys={sorted(kwargs.keys())} config={kwargs.get('config')!r} run_manager={kwargs.get('run_manager')!r}"


async def test_config_argument_survives_ainvoke():
    tool = _make_tool(
        _echo,
        {
            "config": {"type": "object"},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
    )
    result = await tool.ainvoke({"config": {"x": 1}, "tags": ["dev"]})
    assert "config={'x': 1}" in result
    assert "tags" in result


async def test_config_none_is_preserved():
    tool = _make_tool(_echo, {"config": {"type": "object"}})
    result = await tool.ainvoke({"config": None})
    assert "config=None" in result


async def test_no_config_arg_not_injected():
    """Absent config must stay absent — langchain must not inject ``config=None``."""
    tool = _make_tool(_echo, {"tags": {"type": "array"}})
    result = await tool.ainvoke({"tags": ["dev"]})
    # keys must be exactly ["tags"]; a synthetic config=None would leak through
    # as an injected key (langchain arun injects only when the signature
    # advertises a config param, which the override must not).
    assert result == "keys=['tags'] config=None run_manager=None"


async def test_run_manager_argument_survives_ainvoke():
    tool = _make_tool(_echo, {"run_manager": {"type": "string"}})
    result = await tool.ainvoke({"run_manager": "rm1"})
    assert "run_manager='rm1'" in result


async def test_dot_path_key_survives():
    """Flattened deep schemas expose dot-path keys (e.g. ``config.a``); they
    must pass through as-is, not be treated as the reserved ``config`` name."""
    tool = _make_tool(_echo, {"config.a": {"type": "integer"}})
    result = await tool.ainvoke({"config.a": 1})
    assert "config.a" in result


async def test_plain_arguments_unaffected():
    tool = _make_tool(
        _echo,
        {"query": {"type": "string"}, "limit": {"type": "integer"}},
    )
    result = await tool.ainvoke({"query": "q", "limit": 5})
    assert "keys=['limit', 'query']" in result


async def test_sync_only_tool_still_invokes():
    """A StructuredTool without a coroutine (coroutine=None) must still invoke
    through the default path without regressions for non-reserved args."""
    captured: dict[str, Any] = {}

    def _run(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "ok"

    tool = SafeStructuredTool.from_function(
        func=_run,
        name="sync_t",
        description="d",
        args_schema={"type": "object", "properties": {"foo": {"type": "string"}}},
    )
    result = await tool.ainvoke({"foo": "bar"})
    assert result == "ok"
    assert captured == {"foo": "bar"}


def test_config_and_run_manager_survive_sync_invoke():
    """Sync ``invoke`` must not swallow ``config``/``run_manager`` either.

    ``StructuredTool._run`` declares the same keyword-only ``config``/
    ``run_manager`` parameters as ``_arun``; the ``_run`` override keeps them
    inside ``kwargs`` so the sync callable receives them verbatim.
    """
    captured: dict[str, Any] = {}

    def _sync(**kwargs: Any) -> str:
        captured.update(kwargs)
        return (
            f"keys={sorted(kwargs.keys())} "
            f"config={kwargs.get('config')!r} run_manager={kwargs.get('run_manager')!r}"
        )

    tool = SafeStructuredTool.from_function(
        func=_sync,
        name="sync_t",
        description="d",
        args_schema={
            "type": "object",
            "properties": {
                "config": {"type": "object"},
                "run_manager": {"type": "string"},
            },
        },
    )
    result = tool.invoke({"config": {"x": 1}, "run_manager": "rm1"})
    assert result == "keys=['config', 'run_manager'] config={'x': 1} run_manager='rm1'"
    assert captured == {"config": {"x": 1}, "run_manager": "rm1"}


async def test_sync_only_tool_async_invoke_preserves_reserved_args():
    """coroutine=None tools fall back to ``_run`` via ``run_in_executor``; the
    ``config`` argument must survive that path too (not be swallowed by the
    inherited ``StructuredTool._run`` signature)."""
    captured: dict[str, Any] = {}

    def _sync(**kwargs: Any) -> str:
        captured.update(kwargs)
        return f"keys={sorted(kwargs.keys())} config={kwargs.get('config')!r}"

    tool = SafeStructuredTool.from_function(
        func=_sync,
        name="sync_t",
        description="d",
        args_schema={"type": "object", "properties": {"config": {"type": "object"}}},
    )
    result = await tool.ainvoke({"config": {"y": 2}})
    assert result == "keys=['config'] config={'y': 2}"
    assert captured == {"config": {"y": 2}}


def test_sync_invoke_without_func_raises_not_implemented():
    tool = SafeStructuredTool(
        name="t",
        description="d",
        args_schema={"type": "object", "properties": {}},
    )
    with pytest.raises(NotImplementedError):
        tool.invoke({})


async def test_is_structured_tool_instance():
    """SafeStructuredTool must remain a drop-in StructuredTool subclass."""
    from langchain_core.tools import StructuredTool

    tool = _make_tool(_echo, {"x": {"type": "integer"}})
    assert isinstance(tool, StructuredTool)


async def test_tool_call_dict_input_preserves_config_ainvoke():
    """LangGraph ToolNode drives tools with ``{"type": "tool_call", "args": ...}``
    dicts (``_execute_tool_async`` → ``tool.ainvoke(call_args, config)``); a
    ``config`` key nested inside ``args`` must survive that exact production shape.
    """
    captured: dict[str, Any] = {}

    async def _echo_capture(**kwargs: Any) -> str:
        captured.update(kwargs)
        return f"keys={sorted(kwargs.keys())} config={kwargs.get('config')!r}"

    tool = _make_tool(
        _echo_capture,
        {"config": {"type": "object"}, "tags": {"type": "array"}},
    )
    call = {
        "type": "tool_call",
        "name": "t",
        "id": "call_1",
        "args": {"config": {"env": "prod"}, "tags": ["ops"]},
    }
    result = await tool.ainvoke(call)
    assert "config={'env': 'prod'}" in result.content
    assert captured == {"config": {"env": "prod"}, "tags": ["ops"]}


def test_tool_call_dict_input_preserves_config_invoke():
    """Sync ToolNode path (``_execute_tool_sync`` → ``tool.invoke(call_args, config)``)
    must preserve ``config`` the same way as the async path."""
    captured: dict[str, Any] = {}

    def _sync(**kwargs: Any) -> str:
        captured.update(kwargs)
        return f"keys={sorted(kwargs.keys())} config={kwargs.get('config')!r}"

    tool = SafeStructuredTool.from_function(
        func=_sync,
        name="sync_t",
        description="d",
        args_schema={"type": "object", "properties": {"config": {"type": "object"}}},
    )
    result = tool.invoke(
        {
            "type": "tool_call",
            "name": "sync_t",
            "id": "call_2",
            "args": {"config": {"y": 2}},
        }
    )
    assert "keys=['config'] config={'y': 2}" in result.content
    assert captured == {"config": {"y": 2}}


async def test_sync_only_tool_tool_call_input_async_preserves_config():
    """ToolNode async path on a coroutine-less tool falls back to ``invoke`` via
    ``run_in_executor``; the ToolCall dict must still preserve ``config``."""
    captured: dict[str, Any] = {}

    def _sync(**kwargs: Any) -> str:
        captured.update(kwargs)
        return f"keys={sorted(kwargs.keys())} config={kwargs.get('config')!r}"

    tool = SafeStructuredTool.from_function(
        func=_sync,
        name="sync_t",
        description="d",
        args_schema={"type": "object", "properties": {"config": {"type": "object"}}},
    )
    result = await tool.ainvoke(
        {
            "type": "tool_call",
            "name": "sync_t",
            "id": "call_3",
            "args": {"config": {"y": 9}},
        }
    )
    assert "keys=['config'] config={'y': 9}" in result.content
    assert captured == {"config": {"y": 9}}


async def test_runnable_config_does_not_clobber_tool_config():
    """Passing a real RunnableConfig alongside a ``config``-named tool argument
    must not overwrite the user value: the override never advertises a config
    param, so runnable internals stay out of kwargs and the tool argument wins."""
    captured: dict[str, Any] = {}

    async def _echo_capture(**kwargs: Any) -> str:
        captured.update(kwargs)
        return f"keys={sorted(kwargs.keys())} config={kwargs.get('config')!r}"

    tool = _make_tool(_echo_capture, {"config": {"type": "object"}})
    result = await tool.ainvoke(
        {"config": {"x": 1}},
        config={"tags": ["t1"], "metadata": {"k": "v"}},
    )
    assert "config={'x': 1}" in result
    assert captured == {"config": {"x": 1}}


def test_pydantic_schema_config_preserved():
    """When ``args_schema`` is a Pydantic model, a ``config`` field must survive
    sync invoke identically — the fix is signature-level, schema-shape agnostic."""
    from pydantic import BaseModel

    class _In(BaseModel):
        config: dict[str, Any]
        query: str

    captured: dict[str, Any] = {}

    def _sync(**kwargs: Any) -> str:
        captured.update(kwargs)
        return f"keys={sorted(kwargs.keys())} config={kwargs.get('config')!r}"

    tool = SafeStructuredTool.from_function(
        func=_sync,
        name="pyd_t",
        description="d",
        args_schema=_In,
    )
    result = tool.invoke({"config": {"z": 3}, "query": "q"})
    assert result == "keys=['config', 'query'] config={'z': 3}"
    assert captured == {"config": {"z": 3}, "query": "q"}
