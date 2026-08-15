"""Unit tests for structured_tool.py — SafeStructuredTool reserved-name handling.

``langchain_core`` ``BaseTool._arun`` declares ``config``/``run_manager`` as
keyword-only parameters; a tool argument named ``config`` would be silently
bound into the ``_arun`` slot and dropped from the dispatched kwargs.
``SafeStructuredTool`` overrides ``_arun`` with a pure ``*args``/``**kwargs``
signature so every argument reaches the coroutine verbatim. These tests pin
that behavior across value/missing/None/dot-path shapes.
"""

from __future__ import annotations

from typing import Any

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


async def test_is_structured_tool_instance():
    """SafeStructuredTool must remain a drop-in StructuredTool subclass."""
    from langchain_core.tools import StructuredTool

    tool = _make_tool(_echo, {"x": {"type": "integer"}})
    assert isinstance(tool, StructuredTool)
