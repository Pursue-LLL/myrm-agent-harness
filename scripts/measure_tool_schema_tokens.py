#!/usr/bin/env python3
"""Measure detailed tool schema token contributions (tiktoken planning SSOT).

Inspects both Tool Description and Tool JSON Schema parameters (args_schema)
for registered tools across CORE, HIGH_FREQUENCY, and EXTENDED layers.

Usage:
    python scripts/measure_tool_schema_tokens.py
    python scripts/measure_tool_schema_tokens.py --json
    python scripts/measure_tool_schema_tokens.py --all-registered

[INPUT]
- myrm_agent_harness.agent.tool_management.tool_layers (POS: Tool layer sorting and grouping)
- myrm_agent_harness.utils.text_utils (POS: Token counting utility with planning encoding)
- myrm_agent_harness.utils.token_estimation (POS: Token estimation constants)

[OUTPUT]
- measure_single_tool_tokens: Granular token measurement for a single tool
- measure_turn1_tool_schema_tokens: Granular token breakdown report for Turn-1 default tools
- main: CLI entry point for token schema measurement

[POS]
Granular tool schema token measurement script. Measures Tool Description, JSON Schema parameters,
and wrapper token contributions for registered agent tools.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

_repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_repo_root))
sys.path.insert(0, str(_repo_root / "src"))

from myrm_agent_harness.agent.tool_management.tool_layers import (  # noqa: E402
    _TOOL_LAYERS,
    get_tool_layer,
)
from myrm_agent_harness.utils.text_utils import PLANNING_ENCODING, get_token_count  # noqa: E402
from myrm_agent_harness.utils.token_estimation import (  # noqa: E402
    SCHEMA_WRAPPER_TOKENS_PER_TOOL,
)

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool


def measure_single_tool_tokens(tool: BaseTool) -> dict[str, Any]:
    """Measure granular token breakdown for a single tool."""
    desc_str = tool.description or ""
    desc_tokens = get_token_count(desc_str)

    # Measure args_schema / parameters schema JSON tokens
    schema_dict: dict[str, Any] = {}
    if hasattr(tool, "args_schema") and tool.args_schema is not None:
        try:
            if hasattr(tool.args_schema, "model_json_schema"):
                schema_dict = tool.args_schema.model_json_schema()
            elif hasattr(tool.args_schema, "schema"):
                schema_dict = tool.args_schema.schema()
        except Exception:
            schema_dict = {}
    elif hasattr(tool, "args") and isinstance(tool.args, dict):
        schema_dict = tool.args

    schema_json = json.dumps(schema_dict, ensure_ascii=False) if schema_dict else ""
    schema_params_tokens = get_token_count(schema_json) if schema_json else 0

    total_tokens = desc_tokens + schema_params_tokens + SCHEMA_WRAPPER_TOKENS_PER_TOOL

    layer = get_tool_layer(tool.name)
    layer_name = layer.name if hasattr(layer, "name") else str(layer)

    return {
        "name": tool.name,
        "layer": layer_name,
        "description_tokens": desc_tokens,
        "schema_params_tokens": schema_params_tokens,
        "wrapper_tokens": SCHEMA_WRAPPER_TOKENS_PER_TOOL,
        "total_tokens": total_tokens,
    }


async def measure_turn1_tool_schema_tokens() -> dict[str, Any]:
    """Measure Turn-1 default tool profile with schema parameters breakdown."""
    from scripts.measure_turn1_token_inventory import _build_default_turn1_tools

    tools = await _build_default_turn1_tools()
    results: list[dict[str, Any]] = []
    layer_totals: dict[str, int] = defaultdict(int)

    for tool in sorted(tools, key=lambda t: t.name):
        row = measure_single_tool_tokens(tool)
        results.append(row)
        layer_totals[row["layer"]] += row["total_tokens"]

    total_turn1_tokens = sum(r["total_tokens"] for r in results)

    return {
        "encoding": PLANNING_ENCODING,
        "tool_count": len(tools),
        "tools": results,
        "layer_totals": dict(layer_totals),
        "total_tokens": total_turn1_tokens,
    }


def _print_report(report: dict[str, Any]) -> None:
    print(f"Tool Schema Token Inventory Report ({report['encoding']})")
    print(f"Total resolved tools: {report['tool_count']}")
    print()
    print(f"{'Tool Name':<32} {'Layer':<10} {'Desc':>6} {'Schema':>8} {'Wrap':>6} {'Total':>8}")
    print("-" * 74)
    for row in report["tools"]:
        print(
            f"{row['name']:<32} "
            f"{row['layer']:<10} "
            f"{row['description_tokens']:>6} "
            f"{row['schema_params_tokens']:>8} "
            f"{row['wrapper_tokens']:>6} "
            f"{row['total_tokens']:>8}"
        )
    print("-" * 74)
    for layer, subtotal in report["layer_totals"].items():
        print(f"{layer + ' subtotal':<58} {subtotal:>8}")
    print(f"{'Turn-1 Total Budget':<58} {report['total_tokens']:>8}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure detailed tool schema token contributions"
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit JSON output"
    )
    args = parser.parse_args()

    report = asyncio.run(measure_turn1_tool_schema_tokens())
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        _print_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
