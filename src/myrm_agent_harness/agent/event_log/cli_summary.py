"""[INPUT]
- (none)

[OUTPUT]
- generate_cli_summary: Generate a geek-friendly CLI summary table for a session.

[POS]
Provides generate_cli_summary.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def generate_cli_summary(session_id: str, summary_data: dict[str, Any]) -> str:
    """Generate a geek-friendly CLI summary table for a session."""

    lines = []
    lines.append("=" * 60)
    lines.append(f" SESSION SUMMARY: {session_id}")
    lines.append("=" * 60)

    # 1. Execution Overview
    duration_ms = summary_data.get("duration_ms", 0)
    duration_s = duration_ms / 1000.0
    lines.append(f" Total Duration:  {duration_s:.2f}s")
    lines.append(f" Total Events:    {summary_data.get('total_events', 0)}")
    lines.append(f" Tool Calls:      {summary_data.get('tool_call_count', 0)}")
    lines.append(f" Errors:          {summary_data.get('error_count', 0)}")

    runtime_skills = summary_data.get("runtime_skills")
    runtime_tools = summary_data.get("runtime_tools")
    if runtime_skills is not None or runtime_tools is not None:
        lines.append(f" Runtime Skills:  {runtime_skills or 0}")
        lines.append(f" Runtime Tools:   {runtime_tools or 0}")

    lines.append("-" * 60)

    # 2. Token Economics
    token_eco = summary_data.get("token_economics", {})
    if token_eco:
        usage = token_eco.get("usage", {})
        latency = token_eco.get("latency", {})

        lines.append(" TOKEN ECONOMICS")
        lines.append(f"   Cost (USD):    ${token_eco.get('total_cost_usd', 0):.4f}")
        savings = token_eco.get("total_cache_savings_usd", 0)
        if savings > 0:
            lines.append(f"   Cache Savings: ${savings:.4f}")

        lines.append(f"   Input Tokens:  {usage.get('prompt_tokens', 0)}")
        lines.append(f"   Output Tokens: {usage.get('completion_tokens', 0)}")
        lines.append(f"   Cached Tokens: {usage.get('cached_tokens', 0)}")

        lines.append(" LATENCY METRICS")
        lines.append(f"   Avg TTFT:      {latency.get('avg_ttft_ms', 0):.0f}ms")
        lines.append(f"   P95 Latency:   {latency.get('p95_ms', 0):.0f}ms")
        lines.append(f"   Tokens/Sec:    {latency.get('avg_tokens_per_second', 0):.1f}")
        lines.append("-" * 60)

        # 3. Model Breakdown
        model_bd = token_eco.get("model_breakdown", {})
        if model_bd:
            lines.append(" MODEL BREAKDOWN")
            lines.append(f"   {'Model':<30} | {'Tokens':<10} | {'Cost':<10}")
            lines.append(f"   {'-' * 30}-+-{'-' * 10}-+-{'-' * 10}")
            for model, data in model_bd.items():
                short_model = model.split("/")[-1][:30]
                tokens = data.get("total_tokens", 0)
                cost = f"${data.get('cost_usd', 0):.4f}"
                lines.append(f"   {short_model:<30} | {tokens:<10} | {cost:<10}")
            lines.append("-" * 60)

    # 4. Task Metrics (Context Compaction)
    task_metrics = summary_data.get("task_metrics", {})
    if task_metrics:
        lines.append(" CONTEXT METRICS")
        lines.append(f"   Compactions:   {task_metrics.get('compression_count', 0)}")
        lines.append(f"   Saved Tokens:  {task_metrics.get('tokens_saved', 0)}")
        lines.append("-" * 60)

    lines.append("=" * 60)

    return "\n".join(lines)
