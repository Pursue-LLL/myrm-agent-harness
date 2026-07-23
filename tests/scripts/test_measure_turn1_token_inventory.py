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


def test_token_count_empty_string_returns_zero() -> None:
    encoding = MagicMock()
    assert measure._token_count("", encoding) == 0
    encoding.encode.assert_not_called()


def test_token_count_delegates_to_encoding() -> None:
    encoding = MagicMock()
    encoding.encode.return_value = [1, 2, 3]
    assert measure._token_count("hello", encoding) == 3


def test_tool_description_tokens_uses_tool_description() -> None:
    encoding = MagicMock()
    encoding.encode.return_value = [1, 2]
    tool = MagicMock()
    tool.description = "do work"
    assert measure._tool_description_tokens(tool, encoding) == 2


def test_print_table_renders_layer_subtotals(capsys: pytest.CaptureFixture[str]) -> None:
    report = {
        "encoding": "cl100k_base",
        "tool_count": 2,
        "per_tool": [
            {"name": "alpha_tool", "layer": "CORE", "tokens": 10},
            {"name": "beta_tool", "layer": "COMMON", "tokens": 5},
        ],
        "layer_totals": {"CORE": 10, "COMMON": 5},
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
    assert report["schema_wrapper_tokens"] == 2 * measure.SCHEMA_WRAPPER_TOKENS_PER_TOOL
    assert report["tools_subtotal"] == report["description_tokens"] + report["schema_wrapper_tokens"]


def test_main_json_mode(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    fake_report = {
        "encoding": "cl100k_base",
        "tool_count": 0,
        "per_tool": [],
        "layer_totals": {},
        "description_tokens": 0,
        "schema_wrapper_tokens": 0,
        "tools_subtotal": 0,
    }
    monkeypatch.setattr(measure, "measure_turn1_inventory", AsyncMock(return_value=fake_report))
    monkeypatch.setattr(measure.sys, "argv", ["measure_turn1_token_inventory.py", "--json"])
    rc = measure.main()
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["tool_count"] == 0


def test_main_table_mode(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    fake_report = {
        "encoding": "cl100k_base",
        "tool_count": 1,
        "per_tool": [{"name": "solo_tool", "layer": "CORE", "tokens": 42}],
        "layer_totals": {"CORE": 42},
        "description_tokens": 42,
        "schema_wrapper_tokens": 65,
        "tools_subtotal": 107,
    }
    monkeypatch.setattr(measure, "measure_turn1_inventory", AsyncMock(return_value=fake_report))
    monkeypatch.setattr(measure.sys, "argv", ["measure_turn1_token_inventory.py"])
    rc = measure.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "solo_tool" in out
    assert "Tools layer total" in out


@pytest.mark.asyncio
async def test_build_default_turn1_tools_resolves_default_profile() -> None:
    """Smoke: default product profile resolves 15 Turn-1 tools (P3 baseline)."""
    tools = await measure._build_default_turn1_tools()
    names = {tool.name for tool in tools}
    assert len(tools) == 14
    assert "web_search_tool" in names
    assert "bash_code_execute_tool" in names
    assert "dispatch_research" not in names
    assert "spawn_subagent" not in names


# SSOT: DEFAULT_AGENT_TOKEN_INVENTORY.md §二–§四 (2026-07-23 file_edit batch + file_read trim)
_DOC_TURN1_TOOL_TOKENS: dict[str, int] = {
    "web_fetch_tool": 70,
    "bash_code_execute_tool": 808,
    "bash_process_tool": 58,
    "file_edit_tool": 184,
    "file_read_tool": 420,
    "file_write_tool": 153,
    "glob_tool": 263,
    "grep_tool": 344,
    "web_search_tool": 1175,
    "memory_search_tool": 204,
    "memory_save_tool": 688,
    "memory_manage_tool": 247,
    "skill_select_tool": 295,
    "skill_manage_tool": 251,
}


@pytest.mark.asyncio
async def test_measure_turn1_inventory_matches_documented_token_baseline() -> None:
    """Lock measure script output to inventory doc — prevents silent doc drift."""
    report = await measure.measure_turn1_inventory()
    measured = {row["name"]: int(row["tokens"]) for row in report["per_tool"]}
    assert measured == _DOC_TURN1_TOOL_TOKENS
    assert report["tool_count"] == 14
    assert report["description_tokens"] == sum(_DOC_TURN1_TOOL_TOKENS.values())
    assert report["tools_subtotal"] == report["description_tokens"] + report["schema_wrapper_tokens"]
    layer_totals = report["layer_totals"]
    assert layer_totals["CORE"] == 2242
    assert layer_totals["COMMON"] == 2314
    assert layer_totals["EXTENDED"] == 604
    assert report["tools_subtotal"] == 6070
