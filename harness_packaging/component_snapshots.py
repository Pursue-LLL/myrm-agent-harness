"""Component Snapshot Bounded Diff Engine for Myrm Agent Harness.

Exports deterministic JSON snapshots of the 4 core architecture surfaces and
computes bounded semantic diffs to prevent silent behavioral/schema drift.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

def get_snapshots_dir() -> Path:
    """Return the path to the snapshots storage directory."""
    return Path(__file__).resolve().parent / "snapshots"


def export_tool_surface_snapshot() -> list[dict[str, Any]]:
    """Export the sorted list of declared tools with layer allocations."""
    items: list[dict[str, Any]] = []
    for name, layer in sorted(_TOOL_LAYERS.items(), key=lambda pair: (pair[1].value, pair[0])):
        items.append({
            "name": name,
            "layer": layer.name,
            "layer_value": layer.value,
        })
    return items


def export_middleware_stack_snapshot() -> list[dict[str, Any]]:
    """Export the canonical middleware stack registered in harness."""
    from myrm_agent_harness.agent import middlewares as mw

    middleware_symbols = [
        "debug_logger_middleware",
        "tool_interceptor_middleware",
        "FilesystemFileSearchMiddleware",
        "create_context_pipeline_middleware",
        "create_concurrency_limiter",
        "create_safety_dispatcher",
        "PlanConfirmMiddleware",
        "goal_focus_middleware",
        "subagent_limit_middleware",
        "replan_middleware",
        "moa_advisor_middleware",
        "progress_middleware",
        "clarification_guard_middleware",
    ]
    exported: list[dict[str, Any]] = []
    for sym in sorted(middleware_symbols):
        has_symbol = hasattr(mw, sym)
        exported.append({
            "symbol": sym,
            "present": has_symbol,
            "type": "class" if sym.endswith("Middleware") else "function",
        })
    return exported


def export_context_strategies_snapshot() -> list[dict[str, Any]]:
    """Export canonical context management strategies and operators."""
    from myrm_agent_harness.agent.context_management.strategies import summary as summ

    summary_exports = [
        "FOCUS_TOPIC_SUFFIX",
        "SUMMARY_MERGE_PROMPT_TEMPLATE",
        "SUMMARY_PROMPT_TEMPLATE",
        "UNVERIFIED_CONTEXT_MARKER",
        "extract_protected_head",
        "generate_structured_summary",
        "is_summarize_circuit_open",
        "should_summarize",
    ]
    items: list[dict[str, Any]] = []
    for sym in sorted(summary_exports):
        items.append({
            "strategy": "summary",
            "symbol": sym,
            "present": hasattr(summ, sym),
        })
    return items


def export_system_defaults_snapshot() -> dict[str, Any]:
    """Export default agent execution constants and config shapes."""
    from myrm_agent_harness.agent.config.file_io import DEFAULT_FILE_IO_CONFIG
    from myrm_agent_harness.agent.config.llm import AgentConfig, LLMConfig

    default_llm = LLMConfig(model="mock-provider/mock-model", api_key="mock-key")
    default_agent = AgentConfig(llm=default_llm)
    return {
        "agent_config_defaults": {
            "recursion_limit": default_agent.recursion_limit,
            "timeout_seconds": default_agent.timeout_seconds,
            "enable_artifacts": default_agent.enable_artifacts,
            "system_prompt": default_agent.system_prompt,
        },
        "file_io_defaults": {
            "max_file_size_bytes": DEFAULT_FILE_IO_CONFIG.max_file_size_bytes,
            "max_concurrent_reads": DEFAULT_FILE_IO_CONFIG.max_concurrent_reads,
            "max_path_depth": DEFAULT_FILE_IO_CONFIG.max_path_depth,
            "follow_symlinks": DEFAULT_FILE_IO_CONFIG.follow_symlinks,
        },
    }


def export_all_snapshots() -> dict[str, Any]:
    """Export all 4 component snapshots as a dictionary."""
    return {
        "tool_surface": export_tool_surface_snapshot(),
        "middleware_stack": export_middleware_stack_snapshot(),
        "context_strategies": export_context_strategies_snapshot(),
        "system_defaults": export_system_defaults_snapshot(),
    }


def compute_bounded_diff(current: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    """Compute semantic differences between current export and baseline snapshot."""
    diffs: list[str] = []

    # 1. Tool surface diff
    curr_tools = {item["name"]: item for item in current.get("tool_surface", [])}
    base_tools = {item["name"]: item for item in baseline.get("tool_surface", [])}

    added_tools = set(curr_tools) - set(base_tools)
    removed_tools = set(base_tools) - set(curr_tools)
    if added_tools:
        diffs.append(f"Tool Surface: Added tools: {sorted(added_tools)}")
    if removed_tools:
        diffs.append(f"Tool Surface: Removed tools: {sorted(removed_tools)}")

    for common in sorted(set(curr_tools) & set(base_tools)):
        if curr_tools[common]["layer"] != base_tools[common]["layer"]:
            diffs.append(
                f"Tool Surface: Layer mismatch for '{common}': "
                f"current={curr_tools[common]['layer']} vs baseline={base_tools[common]['layer']}"
            )

    # 2. Middleware stack diff
    curr_mw = {item["symbol"]: item for item in current.get("middleware_stack", [])}
    base_mw = {item["symbol"]: item for item in baseline.get("middleware_stack", [])}
    if set(curr_mw) != set(base_mw):
        diffs.append(f"Middleware Stack: Symbol set changed: {set(curr_mw) ^ set(base_mw)}")

    # 3. Context strategies diff
    curr_ctx = {item["symbol"]: item for item in current.get("context_strategies", [])}
    base_ctx = {item["symbol"]: item for item in baseline.get("context_strategies", [])}
    if set(curr_ctx) != set(base_ctx):
        diffs.append(f"Context Strategies: Symbol set changed: {set(curr_ctx) ^ set(base_ctx)}")

    # 4. System defaults diff
    curr_sys = current.get("system_defaults", {})
    base_sys = baseline.get("system_defaults", {})
    if curr_sys != base_sys:
        diffs.append(f"System Defaults: Configuration mismatch:\n  Current: {curr_sys}\n  Baseline: {base_sys}")

    return diffs


def save_snapshots_to_disk(target_dir: Path | None = None) -> None:
    """Save the 4 snapshot files to target directory."""
    out_dir = target_dir or get_snapshots_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    data = export_all_snapshots()
    for key, content in data.items():
        file_path = out_dir / f"{key}_snapshot.json"
        text = json.dumps(content, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        file_path.write_text(text, encoding="utf-8")
