#!/usr/bin/env python3
"""Measure default GeneralAgent Turn-1 bind_tools token cost (tiktoken planning SSOT).

Builds the harness-side default product profile:
  web_search + web_fetch + file_ops (5) + bash + bash_process + memory (3, COMMON)
  + skill_select (when demo skill present)
  (conversation_search opt-in via server; excluded from default Turn1)
  (TSM v1: no request_answer_user_tool, no todo_write; skill_manage opt-in via server)

Usage:
    python scripts/measure_turn1_token_inventory.py
    python scripts/measure_turn1_token_inventory.py --json
"""

from __future__ import annotations
from myrm_agent_harness.agent.meta_tools.mount_policy import FileAccessMode

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

_repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_repo_root))

from myrm_agent_harness.utils.text_utils import PLANNING_ENCODING, get_token_count
from myrm_agent_harness.utils.token_estimation import (
    SCHEMA_WRAPPER_TOKENS_PER_TOOL,
    estimate_bound_tools_tokens,
)

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

ENCODING_NAME = PLANNING_ENCODING


def _tool_description_tokens(tool: BaseTool) -> int:
    return get_token_count(tool.description or "")


async def _build_default_turn1_tools() -> list[BaseTool]:
    from myrm_agent_harness.agent._internals._agent_build import (
        build_middlewares,
        build_tools,
        create_registry,
    )
    from myrm_agent_harness.agent.meta_tools import get_meta_tools
    from myrm_agent_harness.backends.skills.types import SkillMetadata
    from myrm_agent_harness.toolkits.memory.config import MemoryConfig
    from myrm_agent_harness.toolkits.memory.manager import MemoryManager
    from myrm_agent_harness.toolkits.memory.memory_agent_tools import (
        create_memory_tools,
    )
    from myrm_agent_harness.toolkits.web_fetch.web_fetch_agent_tools import (
        create_web_fetch_tool,
    )
    from myrm_agent_harness.toolkits.web_search.engine import SearchServiceConfig
    from myrm_agent_harness.toolkits.web_search.web_search_agent_tools import (
        create_web_search_tool,
    )

    sample_skill = SkillMetadata(
        name="demo_skill",
        description="Demo skill for token inventory measurement",
        model_invocable=True,
        available=True,
    )

    skill_backend = MagicMock()
    skill_backend.load_skill = MagicMock()

    registry = create_registry()
    meta_tools = get_meta_tools(
        [sample_skill],
        skill_backend,
        registry=registry,
        file_access_mode=FileAccessMode.FULL,
        enable_shell_tools=True,
        enable_answer_tool=False,
    )

    search_cfg = SearchServiceConfig(
        search_service="tavily", api_key="measurement-placeholder"
    )
    web_tools = [
        create_web_search_tool(search_cfg),
        create_web_fetch_tool(),
    ]

    memory_config = MemoryConfig(
        embedding_model="test-model",
        collection_prefix="measure_turn1",
        bm25_top_k=50,
        bm25_max_corpus_size=5000,
    )
    vector_store = AsyncMock()
    vector_store.count = AsyncMock(return_value=0)
    vector_store.scroll = AsyncMock(return_value=([], None))
    vector_store.search = AsyncMock(return_value=[])
    vector_store.upsert = AsyncMock()
    vector_store.delete = AsyncMock()
    vector_store.get = AsyncMock(return_value=None)
    vector_store.close = AsyncMock()

    relational_store = AsyncMock()
    relational_store.get_profile = AsyncMock(return_value=None)
    relational_store.set_profile = AsyncMock()
    relational_store.delete_profile = AsyncMock()
    relational_store.list_profiles = AsyncMock(return_value=[])
    relational_store.count_profiles = AsyncMock(return_value=0)

    memory_manager = MemoryManager(
        memory_config,
        user_id="measure_turn1",
        vector=vector_store,
        embedding=AsyncMock(),
        relational=relational_store,
    )
    memory_tools = create_memory_tools(memory_manager)

    user_tools = list(meta_tools) + web_tools + list(memory_tools)
    middlewares = build_middlewares(registry, [])
    return await build_tools(registry, user_tools, middlewares)


async def measure_turn1_inventory() -> dict[str, object]:
    from myrm_agent_harness.agent.tool_management.tool_layers import (
        get_tool_layer,
    )

    tools = await _build_default_turn1_tools()

    per_tool: list[dict[str, object]] = []
    layer_totals: dict[str, int] = defaultdict(int)

    for tool in sorted(tools, key=lambda t: t.name):
        tokens = _tool_description_tokens(tool)
        layer = get_tool_layer(tool.name)
        layer_key = layer.name if hasattr(layer, "name") else str(layer)
        per_tool.append({"name": tool.name, "layer": layer_key, "tokens": tokens})
        layer_totals[layer_key] += tokens

    tool_count = len(tools)
    description_total = sum(int(row["tokens"]) for row in per_tool)
    schema_wrappers = tool_count * SCHEMA_WRAPPER_TOKENS_PER_TOOL
    tools_subtotal = estimate_bound_tools_tokens(tools)

    return {
        "encoding": ENCODING_NAME,
        "tool_count": tool_count,
        "per_tool": per_tool,
        "layer_totals": dict(layer_totals),
        "description_tokens": description_total,
        "schema_wrapper_tokens": schema_wrappers,
        "tools_subtotal": tools_subtotal,
    }


def _print_table(report: dict[str, object]) -> None:
    print(f"Turn-1 default profile measurement ({report['encoding']})")
    print(f"Resolved tools: {report['tool_count']}")
    print()
    print(f"{'Tool':<32} {'Layer':<10} {'Tokens':>8}")
    print("-" * 54)
    for row in report["per_tool"]:
        assert isinstance(row, dict)
        print(f"{row['name']:<32} {row['layer']:<10} {row['tokens']:>8}")
    print("-" * 54)
    layer_totals = report["layer_totals"]
    assert isinstance(layer_totals, dict)
    for layer in ("CORE", "COMMON", "EXTENDED", "EXTERNAL"):
        if layer in layer_totals:
            print(f"{layer + ' subtotal':<42} {layer_totals[layer]:>8}")
    print(f"{'Description subtotal':<42} {report['description_tokens']:>8}")
    print(f"{'Schema wrappers (~65/tool)':<42} {report['schema_wrapper_tokens']:>8}")
    print(f"{'Tools layer total':<42} {report['tools_subtotal']:>8}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure default Turn-1 tool token inventory"
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit JSON instead of a table"
    )
    args = parser.parse_args()

    report = asyncio.run(measure_turn1_inventory())
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_table(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
