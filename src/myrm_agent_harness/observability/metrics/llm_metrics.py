"""LLM calling monitoring metrics.

Provides通用LLM调用监控指标，适用于任何使用Myrm框架的项目。

[INPUT]
- (none — pure metrics definition)

[OUTPUT]
- llm_call_total — Total LLM calls counter
- llm_call_failed_total — LLM failures counter
- llm_token_usage_total — Token consumption counter
- llm_call_duration_seconds — LLM call duration histogram

[POS]
Harness-layer generic LLM monitoring metrics reusable by any Myrm-based project.

"""

from __future__ import annotations

from myrm_agent_harness.observability.metrics import (
    create_counter,
    create_histogram,
)

# LLM call counters
llm_call_total = create_counter(
    "llm_call_total",
    "Total number of LLM calls",
    ("model", "provider"),
)

llm_call_failed_total = create_counter(
    "llm_call_failed_total",
    "Total number of LLM call failures",
    ("model", "error_type"),
)

# LLM token usage
llm_token_usage_total = create_counter(
    "llm_token_usage_total",
    "Total number of tokens consumed",
    ("model", "type"),  # token type: input/output
)

# LLM call duration
llm_call_duration_seconds = create_histogram(
    "llm_call_duration_seconds",
    "LLM call duration in seconds",
    ("model", "provider"),
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60),
)


__all__ = [
    "llm_call_duration_seconds",
    "llm_call_failed_total",
    "llm_call_total",
    "llm_token_usage_total",
]
