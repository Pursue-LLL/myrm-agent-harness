"""Unit tests for scripts.measure_turn1_token_inventory.

Pure helpers are tested directly; the async inventory path uses a stubbed
tool list so we avoid spinning up MemoryManager / web backends in CI.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

import scripts.measure_turn1_token_inventory as measure
from myrm_agent_harness.agent.meta_tools.bash._tool.helpers import get_os_hint
from myrm_agent_harness.agent.meta_tools.bash._tool.tool_description import (
    resolve_bash_code_execute_tool_description,
)
from myrm_agent_harness.utils.text_utils import get_token_count
from myrm_agent_harness.utils.token_estimation import SCHEMA_WRAPPER_TOKENS_PER_TOOL


def test_token_count_empty_string_returns_zero() -> None:
    assert measure._tool_description_tokens(MagicMock(description="")) == 0


def test_tool_description_tokens_uses_tool_description() -> None:
    tool = MagicMock()
    tool.description = "do work"
    tokens = measure._tool_description_tokens(tool)
    assert tokens > 0


def test_print_table_renders_layer_subtotals(
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = {
        "encoding": measure.ENCODING_NAME,
        "tool_count": 2,
        "per_tool": [
            {"name": "alpha_tool", "layer": "CORE", "tokens": 10},
            {"name": "beta_tool", "layer": "HIGH_PRIORITY", "tokens": 5},
        ],
        "layer_totals": {"CORE": 10, "HIGH_PRIORITY": 5},
        "description_tokens": 15,
        "schema_wrapper_tokens": 130,
        "tools_subtotal": 145,
    }
    measure._print_table(report)
    out = capsys.readouterr().out
    assert "alpha_tool" in out
    assert "Tools layer total" in out
    assert "145" in out


@pytest.mark.asyncio
async def test_measure_turn1_inventory_aggregates_stub_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool_a = MagicMock()
    tool_a.name = "z_tool"
    tool_a.description = "zzz"
    tool_b = MagicMock()
    tool_b.name = "a_tool"
    tool_b.description = "aaa"

    monkeypatch.setattr(
        measure,
        "_build_default_turn1_tools",
        AsyncMock(return_value=[tool_a, tool_b]),
    )

    report = await measure.measure_turn1_inventory()
    assert report["tool_count"] == 2
    assert report["encoding"] == measure.ENCODING_NAME
    names = [row["name"] for row in report["per_tool"]]
    assert names == ["a_tool", "z_tool"]
    assert report["schema_wrapper_tokens"] == 2 * SCHEMA_WRAPPER_TOKENS_PER_TOOL
    assert (
        report["tools_subtotal"]
        == report["description_tokens"] + report["schema_wrapper_tokens"]
    )


def test_main_json_mode(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_report = {
        "encoding": measure.ENCODING_NAME,
        "tool_count": 0,
        "per_tool": [],
        "layer_totals": {},
        "description_tokens": 0,
        "schema_wrapper_tokens": 0,
        "tools_subtotal": 0,
    }
    monkeypatch.setattr(
        measure, "measure_turn1_inventory", AsyncMock(return_value=fake_report)
    )
    monkeypatch.setattr(
        measure.sys, "argv", ["measure_turn1_token_inventory.py", "--json"]
    )
    rc = measure.main()
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["tool_count"] == 0


def test_main_table_mode(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_report = {
        "encoding": measure.ENCODING_NAME,
        "tool_count": 1,
        "per_tool": [{"name": "solo_tool", "layer": "CORE", "tokens": 42}],
        "layer_totals": {"CORE": 42},
        "description_tokens": 42,
        "schema_wrapper_tokens": 65,
        "tools_subtotal": 107,
    }
    monkeypatch.setattr(
        measure, "measure_turn1_inventory", AsyncMock(return_value=fake_report)
    )
    monkeypatch.setattr(measure.sys, "argv", ["measure_turn1_token_inventory.py"])
    rc = measure.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "solo_tool" in out
    assert "Tools layer total" in out


@pytest.mark.asyncio
async def test_build_default_turn1_tools_resolves_default_profile() -> None:
    """Smoke: default product profile resolves 13 Turn-1 tools (P3 baseline)."""
    tools = await measure._build_default_turn1_tools()
    names = {tool.name for tool in tools}
    assert len(tools) == 13
    assert "web_search_tool" in names
    assert "bash_code_execute_tool" in names
    assert "skill_select_tool" in names
    assert "skill_manage_tool" not in names
    assert "dispatch_research" not in names
    assert "spawn_subagent" not in names


# SSOT: DEFAULT_AGENT_TOKEN_INVENTORY.md §二–§四 (measure_turn1 default profile, o200k_base)
#
# Host-independent baseline. Every tool except ``bash_code_execute_tool`` produces a
# byte-constant description, so its token count is asserted exactly. The bash tool is
# the one exception: its description is
# ``resolve_bash_code_execute_tool_description(locale) + get_os_hint(locale)``
# (bash_code_execute_tool.py:123), and the OS hint embeds ``os_release`` + ``arch``
# (platform.py:116-122). Its total therefore varies by host (58 on macOS arm64,
# 32 on ubuntu-latest, 31/36 on other Linux flavors) — so the gate pins the
# host-independent static half and subtracts the locally measured hint instead.
_BASH_TOOL_NAME = "bash_code_execute_tool"
_BASH_STATIC_DESCRIPTION_TOKENS = 1368

_DOC_TURN1_TOOL_TOKENS: dict[str, int] = {
    "bash_process_tool": 107,
    "file_edit_tool": 132,
    "file_read_tool": 332,
    "file_write_tool": 118,
    "glob_tool": 201,
    "grep_tool": 205,
    "memory_manage_tool": 359,
    "memory_save_tool": 720,
    "memory_search_tool": 143,
    "skill_select_tool": 240,
    "web_fetch_tool": 148,
    "web_search_tool": 1174,
}


@pytest.mark.asyncio
async def test_measure_turn1_inventory_matches_documented_token_baseline() -> None:
    """Lock measure script output to inventory doc — prevents silent doc drift.

    Host-agnostic: the bash tool's description is ``static + host OS hint``, so the gate
    pins both halves independently. It therefore holds on macOS arm64 (1,425) and
    ubuntu-latest CI (1,399) alike, while still failing on any genuine drift.
    """
    report = await measure.measure_turn1_inventory()
    measured = {str(row["name"]): int(row["tokens"]) for row in report["per_tool"]}

    drifted = {
        name: (measured.get(name), expected)
        for name, expected in _DOC_TURN1_TOOL_TOKENS.items()
        if measured.get(name) != expected
    }
    assert not drifted, (
        "Turn-1 tool description tokens drifted from DEFAULT_AGENT_TOKEN_INVENTORY.md "
        f"(tool: measured vs documented) -> {drifted}"
    )
    assert measured.keys() == {*_DOC_TURN1_TOOL_TOKENS, _BASH_TOOL_NAME}

    # Bash: pin the host-independent static half, then verify the composite really is
    # static + hint (BPE merging at the junction may save exactly one token).
    bash_tokens = measured[_BASH_TOOL_NAME]
    bash_static = get_token_count(resolve_bash_code_execute_tool_description("en"))
    host_hint = get_token_count(get_os_hint("en"))
    assert bash_static == _BASH_STATIC_DESCRIPTION_TOKENS, (
        f"{_BASH_TOOL_NAME} static description drifted (measured vs documented) -> "
        f"{bash_static} vs {_BASH_STATIC_DESCRIPTION_TOKENS}"
    )
    assert bash_tokens - bash_static in (host_hint - 1, host_hint), (
        f"{_BASH_TOOL_NAME} description is not static + host hint "
        f"(composite minus static vs measured hint) -> {bash_tokens - bash_static} vs {host_hint}"
    )

    assert report["tool_count"] == 13
    layer_totals = report["layer_totals"]
    # CORE is host-dependent solely through the bash tool; HIGH_PRIORITY is not.
    assert layer_totals["CORE"] + layer_totals["HIGH_PRIORITY"] == report["description_tokens"]
    assert layer_totals["HIGH_PRIORITY"] == 2636
    assert report["tools_subtotal"] <= 6500, "Turn-1 tools exceeded the 6,500 budget ceiling"
