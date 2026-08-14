"""Live-wire integration tests for inbound tool-argument schema coercion.

Boots a *real* stdio MCP server and drives the production session stack
(``MCPSessionActor`` → ``process_session_tools`` coercion wrapper → real
``call_tool`` wire call) with LLM-style string arguments, asserting the MCP
server actually receives correctly-typed values:

- big integers (≥ 2^53) survive the wire with exact precision;
- float-form big-integer literals (``"9007199254740993.0"``) are normalized
  losslessly instead of degrading through float();
- bare scalars are wrapped into single-element arrays for ``array`` schemas;
- JSON-array strings are parsed and their items coerced;
- numeric 1/0 cross-coerces to boolean;
- unparseable literals stay strings and are rejected by the server's schema
  validation with a readable error (no crash, no silent data corruption).

Nothing on the coercion or wire path is mocked — only the LLM-produced
argument values are simulated, matching the real production contract where the
framework coerces LLM output against the tool's JSON schema.
"""

from __future__ import annotations

import sys

import pytest
import pytest_asyncio

from myrm_agent_harness.toolkits.mcp.session_actor import MCPSessionActor

# A minimal real MCP server whose tool declares the exact production argument
# types (int / float / bool / list[str]) that exercise every coercion path.
_SERVER_SRC = """
import sys

from mcp.server.mcpserver import MCPServer

server = MCPServer("schema-coercion-probe")


@server.tool()
def lookup(
    id: int,
    score: float,
    active: bool,
    tags: list[str],
) -> str:
    return (
        f"id={id} id_type={type(id).__name__} "
        f"score={score} score_type={type(score).__name__} "
        f"active={active!r} active_type={type(active).__name__} "
        f"tags={tags!r} tags_type={type(tags).__name__}"
    )


if __name__ == "__main__":
    server.run(transport="stdio")
"""

# A second real server exposing a nested-object / array / optional-field tool so
# the wire integration also covers recursive coercion, list-item big integers,
# reverse bool→int coercion, and optional-null stripping.
_NESTED_SERVER_SRC = """
import sys
from typing import TypedDict

from mcp.server.mcpserver import MCPServer


class Filter(TypedDict):
    count: int
    active: bool


server = MCPServer("nested-coercion-probe")


@server.tool()
def analyze(filters: Filter, ids: list[int], rank: int, label: str = "default") -> str:
    return (
        f"filters={filters!r} filters_type={type(filters).__name__} "
        f"ids={ids!r} ids_types={[type(i).__name__ for i in ids]} "
        f"rank={rank!r} rank_type={type(rank).__name__} "
        f"label={label!r} label_type={type(label).__name__}"
    )


if __name__ == "__main__":
    server.run(transport="stdio")
"""


@pytest_asyncio.fixture
async def _probe_actor(tmp_path) -> object:
    """A live stdio MCP session exposing the ``lookup`` tool via the actor."""
    script = tmp_path / "coercion_probe_server.py"
    script.write_text(_SERVER_SRC, encoding="utf-8")

    actor = MCPSessionActor(
        "coercion-probe",
        {"transport": "stdio", "command": sys.executable, "args": [str(script)]},
        connect_timeout=20.0,
    )
    await actor.start()
    try:
        yield actor
    finally:
        await actor.close()


@pytest_asyncio.fixture
async def _nested_actor(tmp_path) -> object:
    """A live stdio MCP session exposing the ``analyze`` tool via the actor."""
    script = tmp_path / "nested_coercion_probe_server.py"
    script.write_text(_NESTED_SERVER_SRC, encoding="utf-8")

    actor = MCPSessionActor(
        "nested-coercion-probe",
        {"transport": "stdio", "command": sys.executable, "args": [str(script)]},
        connect_timeout=20.0,
    )
    await actor.start()
    try:
        yield actor
    finally:
        await actor.close()


async def _lookup(actor: object, **params: object) -> str:
    result = await actor.call("lookup", params)  # type: ignore[attr-defined]
    assert isinstance(result, str), result
    return result


async def _analyze(actor: object, **params: object) -> str:
    result = await actor.call("analyze", params)  # type: ignore[attr-defined]
    assert isinstance(result, str), result
    return result


@pytest.mark.asyncio
async def test_big_integer_js_safe_boundary_exact(_probe_actor: object) -> None:
    """2^53 boundary integer survives the wire without float degradation."""
    result = await _lookup(_probe_actor, id="9007199254740993", score="1.5", active=True, tags=["x"])
    assert "id=9007199254740993 id_type=int" in result


@pytest.mark.asyncio
async def test_big_integer_above_2_53_exact(_probe_actor: object) -> None:
    """A 20-digit integer (beyond any JS Number / float64 range) stays exact."""
    result = await _lookup(_probe_actor, id="12345678901234567890", score="1.5", active=True, tags=["x"])
    assert "id=12345678901234567890 id_type=int" in result


@pytest.mark.asyncio
async def test_float_form_big_integer_literal_lossless(_probe_actor: object) -> None:
    """'9007199254740993.0' must normalize to the exact int, not a rounded float."""
    result = await _lookup(_probe_actor, id="9007199254740993.0", score="3.14", active=0, tags=["x"])
    assert "id=9007199254740993 id_type=int" in result
    assert "score=3.14" in result


@pytest.mark.asyncio
async def test_huge_integer_no_float_loss(_probe_actor: object) -> None:
    """A 31-digit integer is sent exactly (float() would round the last digits)."""
    result = await _lookup(_probe_actor, id="1" + "0" * 30, score="1", active=True, tags=["x"])
    assert "id=1000000000000000000000000000000 id_type=int" in result


@pytest.mark.asyncio
async def test_scalar_wrapped_into_single_element_array(_probe_actor: object) -> None:
    """A bare scalar for an array field is wrapped into a one-element list."""
    result = await _lookup(_probe_actor, id="1", score="1", active=True, tags="red")
    assert "tags=['red'] tags_type=list" in result


@pytest.mark.asyncio
async def test_json_array_string_parsed_and_items_coerced(_probe_actor: object) -> None:
    """A JSON-array literal string is parsed and delivered as a real list."""
    result = await _lookup(_probe_actor, id="1", score="1", active=True, tags='["a", "b"]')
    assert "tags=['a', 'b'] tags_type=list" in result


@pytest.mark.asyncio
async def test_numeric_one_cross_coerces_to_boolean(_probe_actor: object) -> None:
    """LLM numeric 1/0 for a boolean field arrives as a real bool."""
    result = await _lookup(_probe_actor, id="1", score="1", active=1, tags=["x"])
    assert "active=True active_type=bool" in result


@pytest.mark.asyncio
async def test_numeric_zero_cross_coerces_to_boolean(_probe_actor: object) -> None:
    """Numeric 0 for a boolean field arrives as False."""
    result = await _lookup(_probe_actor, id="1", score="1", active=0, tags=["x"])
    assert "active=False active_type=bool" in result


@pytest.mark.asyncio
async def test_unparseable_literals_rejected_not_corrupted(_probe_actor: object) -> None:
    """Garbage numeric literals stay strings and the server rejects them with
    a readable schema error — no crash, no silent value corruption."""
    result = await _lookup(_probe_actor, id="abc", score="x", active=True, tags="red")
    assert "int_parsing" in result or "float_parsing" in result or "MCP tool error" in result


@pytest.mark.asyncio
async def test_nested_object_args_recursively_coerced(_nested_actor: object) -> None:
    """Nested object fields are coerced recursively: big-integer strings and
    numeric 1/0 inside a nested dict arrive typed on the server side."""
    result = await _analyze(
        _nested_actor,
        filters={"count": "9007199254740993", "active": 1},
        ids=["1"],
        rank=1,
        label="x",
    )
    assert "filters={'count': 9007199254740993, 'active': True}" in result


@pytest.mark.asyncio
async def test_list_int_items_big_integer_exact(_nested_actor: object) -> None:
    """list[int] items are each coerced — a 2^53-boundary string element
    survives the wire as an exact int, not a rounded float."""
    result = await _analyze(
        _nested_actor,
        filters={"count": 1, "active": True},
        ids=["9007199254740993", "42"],
        rank=1,
        label="x",
    )
    assert "ids=[9007199254740993, 42] ids_types=['int', 'int']" in result


@pytest.mark.asyncio
async def test_bool_to_int_reverse_coercion(_nested_actor: object) -> None:
    """A boolean for an integer field cross-coerces to its numeric 1/0 form."""
    result = await _analyze(
        _nested_actor,
        filters={"count": 1, "active": True},
        ids=["1"],
        rank=True,
        label="x",
    )
    assert "rank=1 rank_type=int" in result


@pytest.mark.asyncio
async def test_optional_null_stripped_server_default_used(_nested_actor: object) -> None:
    """An explicit None for an optional field is stripped before the wire call,
    so the server-side default value is in effect."""
    result = await _analyze(
        _nested_actor,
        filters={"count": 1, "active": True},
        ids=["1"],
        rank=1,
        label=None,
    )
    assert "label='default' label_type=str" in result
